"""Tests for the decision-tree rule extractor (Phase C)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentos.extractor import (
    Predicate,
    Rule,
    Sample,
    _best_split,
    _build_tree,
    _gini,
    extract_rules,
    extract_rules_from_db,
    load_labeled_samples,
)
from agentos.storage import (
    RunRecord,
    ensure_schema,
    record_decision,
    record_outcome,
    record_run,
)


class GiniTestCase(unittest.TestCase):
    def test_gini_empty_is_zero(self) -> None:
        self.assertEqual(_gini([]), 0.0)

    def test_gini_pure_is_zero(self) -> None:
        samples = [Sample({"f": True}, "a") for _ in range(5)]
        self.assertEqual(_gini(samples), 0.0)

    def test_gini_balanced_is_half(self) -> None:
        samples = [Sample({}, "a"), Sample({}, "b")]
        self.assertAlmostEqual(_gini(samples), 0.5)


class BestSplitTestCase(unittest.TestCase):
    def test_returns_none_when_already_pure(self) -> None:
        samples = [Sample({"f": True}, "a") for _ in range(4)]
        self.assertIsNone(_best_split(samples))

    def test_finds_perfect_split(self) -> None:
        samples = [
            Sample({"is_root": True}, "feedback"),
            Sample({"is_root": True}, "feedback"),
            Sample({"is_root": False}, "skip"),
            Sample({"is_root": False}, "skip"),
        ]
        split = _best_split(samples)
        self.assertIsNotNone(split)
        feature, value, gain = split  # type: ignore[misc]
        self.assertEqual(feature, "is_root")
        self.assertGreater(gain, 0)


class ExtractRulesTestCase(unittest.TestCase):
    def test_empty_samples_returns_no_rules(self) -> None:
        self.assertEqual(extract_rules([], decision_key="k"), [])

    def test_unanimous_single_feature_produces_rule(self) -> None:
        # 30 samples where is_root=true → all feedback; 30 where is_root=false → all skip
        samples = (
            [Sample({"is_root": True, "noise": "x"}, "feedback") for _ in range(30)]
            + [Sample({"is_root": False, "noise": "x"}, "skip") for _ in range(30)]
        )
        rules = extract_rules(
            samples, decision_key="k", min_coverage=10, min_precision=1.0,
        )
        # At least one rule should fire on is_root==true → feedback.
        feedback_rules = [r for r in rules if r.chosen == "feedback"]
        self.assertTrue(feedback_rules)
        rule = feedback_rules[0]
        self.assertEqual(rule.precision, 1.0)
        self.assertGreaterEqual(rule.coverage, 30)
        # Predicate must include is_root == True somewhere in the conjunction.
        self.assertTrue(
            any(p.feature == "is_root" and p.value is True for p in rule.predicate),
            f"expected is_root==True in {rule.predicate}",
        )

    def test_min_coverage_filter(self) -> None:
        samples = (
            [Sample({"is_root": True}, "feedback") for _ in range(5)]
            + [Sample({"is_root": False}, "skip") for _ in range(20)]
        )
        # min_coverage=10 should drop the 5-sample feedback leaf
        rules = extract_rules(
            samples, decision_key="k", min_coverage=10, min_precision=1.0,
        )
        for r in rules:
            self.assertGreaterEqual(r.coverage, 10)

    def test_min_precision_filter(self) -> None:
        # Mixed labels — no perfect split possible.
        samples = (
            [Sample({"f": True}, "a") for _ in range(10)]
            + [Sample({"f": True}, "b") for _ in range(8)]  # noise on the same feature value
            + [Sample({"f": False}, "c") for _ in range(15)]
        )
        rules = extract_rules(
            samples, decision_key="k", min_coverage=5, min_precision=1.0,
        )
        # f=true is only 10/18 = 0.55 → below min_precision; f=false is unanimous
        # The extractor should drop the impure leaf and keep the pure one (if any).
        for r in rules:
            self.assertEqual(r.precision, 1.0)

    def test_two_feature_conjunction(self) -> None:
        # Pattern: (sender_is_devops AND has_mention) → feedback. Other combos → skip.
        samples = (
            # 25 unanimous feedback when both features true
            [Sample({"sender_is_devops": True, "has_mention": True}, "feedback")
             for _ in range(25)]
            # 25 unanimous skip when has_mention is false
            + [Sample({"sender_is_devops": True, "has_mention": False}, "skip")
               for _ in range(25)]
            # 25 unanimous skip when sender is not devops
            + [Sample({"sender_is_devops": False, "has_mention": True}, "skip")
               for _ in range(25)]
        )
        rules = extract_rules(
            samples, decision_key="k", min_coverage=20, min_precision=1.0,
        )
        feedback_rules = [r for r in rules if r.chosen == "feedback"]
        self.assertTrue(feedback_rules)
        rule = feedback_rules[0]
        # The feedback predicate must include both features (in some order).
        feats = {(p.feature, p.value) for p in rule.predicate}
        self.assertIn(("sender_is_devops", True), feats)
        self.assertIn(("has_mention", True), feats)

    def test_rule_to_dict_shape(self) -> None:
        samples = [Sample({"f": True}, "a") for _ in range(20)]
        samples += [Sample({"f": False}, "b") for _ in range(20)]
        rules = extract_rules(
            samples, decision_key="k.x", min_coverage=10, min_precision=1.0,
        )
        d = rules[0].to_dict()
        self.assertEqual(d["decision_key"], "k.x")
        self.assertIn("predicate", d)
        self.assertIn("chosen", d)
        self.assertIn("coverage", d)
        self.assertIn("precision", d)
        self.assertIn("support_total", d)
        self.assertIn("support_share", d)


class ExtractRulesFromDBTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.conn = ensure_schema(self.home)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _seed(self, run_id: str, key: str, chosen: str, features: dict) -> None:
        record_run(
            self.conn,
            RunRecord(
                run_id=run_id, intent="t", source="t", command="c",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.010Z",
                exit_code=0, duration_ms=10, trace_path="t",
            ),
        )
        record_decision(
            self.conn, run_id, key,
            {"output": {"chosen": chosen}, "features": features},
            decision_source="decision_file",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_outcome(self.conn, run_id, "success", {})

    def test_load_labeled_samples_skips_decisions_without_features(self) -> None:
        record_run(
            self.conn,
            RunRecord(
                run_id="r1", intent="t", source="t", command="c",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.010Z",
                exit_code=0, duration_ms=10, trace_path="t",
            ),
        )
        record_decision(
            self.conn, "r1", "k",
            {"output": {"chosen": "x"}},  # no features
            decision_source="decision_file",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_outcome(self.conn, "r1", "success", {})
        samples = load_labeled_samples(self.conn, "k")
        self.assertEqual(samples, [])

    def test_extract_rules_from_db_round_trip(self) -> None:
        for i in range(20):
            self._seed(f"run_a{i}", "teams.classify_thread", "feedback",
                       {"is_root": True, "has_mention": True})
        for i in range(20):
            self._seed(f"run_b{i}", "teams.classify_thread", "skip",
                       {"is_root": False, "has_mention": False})

        rules = extract_rules_from_db(
            self.conn,
            decision_key="teams.classify_thread",
            min_coverage=10,
            min_precision=1.0,
        )
        self.assertTrue(rules)
        # At least one perfect feedback rule with the expected predicate.
        feedback = [r for r in rules if r.chosen == "feedback"]
        self.assertTrue(feedback)
        self.assertEqual(feedback[0].precision, 1.0)


if __name__ == "__main__":
    unittest.main()
