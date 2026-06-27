"""Tests for the PURE, storage-agnostic AgentOS kernel.

These tests exercise ``agentos.kernel`` in complete isolation — no SQLite,
no filesystem, no network. They are the proof that the kernel is vendorable
verbatim into Loom (stdlib-only, self-contained): if any of these needed a
DB or a file, the kernel would not be pure.

Coverage:
  * purity guard — the module's source imports nothing but pure stdlib
  * decision/rule schema dataclasses (Sample, Predicate, Rule)
  * CART helpers and rule extraction (in-memory samples only)
  * walk-forward backtest metrics (list[str] only)
  * deterministic rule matching (predicate_matches / match_rule /
    sort_rules_by_specificity)
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from agentos import kernel
from agentos.kernel import (
    Predicate,
    Rule,
    Sample,
    _best_split,
    _build_tree,
    _candidate_splits,
    _class_counts,
    _gini,
    _split_samples,
    _walk_leaves,
    compute_backtest_metrics,
    dominant_choice,
    extract_rules,
    match_rule,
    predicate_matches,
    sort_rules_by_specificity,
)


# ---------------------------------------------------------------------------
# Purity guard — the invariant that makes the kernel vendorable into Loom
# ---------------------------------------------------------------------------

_ALLOWED_TOP_LEVEL_IMPORTS = {
    "__future__",
    "collections",
    "dataclasses",
    "typing",
    "json",
    "math",
}


class KernelPurityTestCase(unittest.TestCase):
    """The kernel must import ONLY pure stdlib — no sqlite3, os, I/O, network."""

    def _kernel_source(self) -> str:
        path = Path(kernel.__file__)
        return path.read_text()

    def test_kernel_imports_only_pure_stdlib(self) -> None:
        tree = ast.parse(self._kernel_source())
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_roots.add(node.module.split(".")[0])
        forbidden = imported_roots - _ALLOWED_TOP_LEVEL_IMPORTS
        self.assertEqual(
            forbidden,
            set(),
            f"kernel.py imports non-pure modules {sorted(forbidden)} — this "
            f"breaks the vendor-into-Loom invariant (stdlib-only, zero I/O).",
        )

    def test_kernel_makes_no_io_calls(self) -> None:
        # AST-level check (robust to docstring mentions): the kernel must not
        # CALL filesystem/network primitives like open()/read()/connect().
        tree = ast.parse(self._kernel_source())
        banned_call_names = {"open", "connect", "urlopen", "system", "popen", "exec"}
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in banned_call_names:
                    offenders.append(name)
        self.assertEqual(
            offenders, [],
            f"kernel.py performs I/O-ish calls {offenders} — it must stay pure.",
        )

    def test_kernel_does_not_import_agentos_or_sqlite_modules(self) -> None:
        # Import-graph check via AST (not substring — docstrings may mention them).
        tree = ast.parse(self._kernel_source())
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        for banned in ("sqlite3", "os", "pathlib", "agentos", "socket", "urllib", "requests"):
            self.assertNotIn(banned, roots, f"kernel.py must not import {banned!r}.")


# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------


class SchemaTestCase(unittest.TestCase):
    def test_predicate_matches_and_to_dict(self) -> None:
        p = Predicate(feature="is_root", value=True)
        self.assertTrue(p.matches({"is_root": True}))
        self.assertFalse(p.matches({"is_root": False}))
        self.assertFalse(p.matches({}))
        self.assertEqual(p.to_dict(), {"feature": "is_root", "op": "==", "value": True})

    def test_rule_to_dict_support_share(self) -> None:
        rule = Rule(
            decision_key="k",
            predicate=[Predicate("is_root", True)],
            chosen="feedback",
            coverage=30,
            precision=1.0,
            support_total=40,
        )
        d = rule.to_dict()
        self.assertEqual(d["decision_key"], "k")
        self.assertEqual(d["chosen"], "feedback")
        self.assertEqual(d["coverage"], 30)
        self.assertEqual(d["precision"], 1.0)
        self.assertEqual(d["support_total"], 40)
        self.assertEqual(d["support_share"], round(30 / 40, 6))
        self.assertEqual(d["predicate"], [{"feature": "is_root", "op": "==", "value": True}])

    def test_rule_support_share_zero_when_no_support_total(self) -> None:
        rule = Rule(
            decision_key="k", predicate=[], chosen="x",
            coverage=5, precision=1.0, support_total=0,
        )
        self.assertEqual(rule.to_dict()["support_share"], 0.0)


# ---------------------------------------------------------------------------
# CART helpers
# ---------------------------------------------------------------------------


class CARTHelpersTestCase(unittest.TestCase):
    def test_class_counts(self) -> None:
        samples = [Sample({}, "a"), Sample({}, "a"), Sample({}, "b")]
        self.assertEqual(_class_counts(samples), {"a": 2, "b": 1})

    def test_gini_empty_is_zero(self) -> None:
        self.assertEqual(_gini([]), 0.0)

    def test_gini_pure_is_zero(self) -> None:
        self.assertEqual(_gini([Sample({}, "a"), Sample({}, "a")]), 0.0)

    def test_gini_balanced_is_half(self) -> None:
        self.assertAlmostEqual(_gini([Sample({}, "a"), Sample({}, "b")]), 0.5)

    def test_split_samples(self) -> None:
        samples = [
            Sample({"x": 1}, "a"),
            Sample({"x": 2}, "b"),
            Sample({}, "c"),
        ]
        match, other = _split_samples(samples, "x", 1)
        self.assertEqual([s.chosen for s in match], ["a"])
        self.assertEqual([s.chosen for s in other], ["b", "c"])

    def test_candidate_splits_skips_high_cardinality(self) -> None:
        # 'id' has 3 distinct values; with max_cardinality=2 it is skipped.
        samples = [
            Sample({"flag": True, "id": "a"}, "x"),
            Sample({"flag": True, "id": "b"}, "x"),
            Sample({"flag": False, "id": "c"}, "y"),
        ]
        cands = _candidate_splits(samples, max_cardinality=2)
        feats = {f for f, _ in cands}
        self.assertIn("flag", feats)
        self.assertNotIn("id", feats)

    def test_best_split_none_when_pure(self) -> None:
        self.assertIsNone(_best_split([Sample({"x": 1}, "a"), Sample({"x": 2}, "a")]))

    def test_best_split_none_when_too_few(self) -> None:
        self.assertIsNone(_best_split([Sample({"x": 1}, "a")]))

    def test_best_split_finds_separating_feature(self) -> None:
        samples = [
            Sample({"flag": True}, "a"),
            Sample({"flag": True}, "a"),
            Sample({"flag": False}, "b"),
            Sample({"flag": False}, "b"),
        ]
        split = _best_split(samples)
        self.assertIsNotNone(split)
        assert split is not None
        self.assertEqual(split[0], "flag")

    def test_build_tree_leaf_when_below_min_split(self) -> None:
        node = _build_tree([Sample({"x": 1}, "a")], max_depth=4, min_split=2)
        self.assertTrue(node.is_leaf)

    def test_walk_leaves_collects_positive_conjunctions(self) -> None:
        samples = [
            Sample({"flag": True}, "a"),
            Sample({"flag": True}, "a"),
            Sample({"flag": False}, "b"),
            Sample({"flag": False}, "b"),
        ]
        tree = _build_tree(samples, max_depth=2, min_split=2)
        leaves = _walk_leaves(tree, predicate=[])
        # At least one leaf carries the positive predicate flag==True.
        carried = [pred for pred, _ in leaves if pred]
        self.assertTrue(any(p[0].feature == "flag" for p in carried))


# ---------------------------------------------------------------------------
# extract_rules — full pipeline on in-memory samples (no DB)
# ---------------------------------------------------------------------------


class ExtractRulesTestCase(unittest.TestCase):
    def test_empty_samples_returns_empty(self) -> None:
        self.assertEqual(extract_rules([], decision_key="k"), [])

    def test_extracts_unanimous_rule(self) -> None:
        # 30 samples with flag=True all chose 'a'; 30 with flag=False chose 'b'.
        samples = (
            [Sample({"flag": True}, "a") for _ in range(30)]
            + [Sample({"flag": False}, "b") for _ in range(30)]
        )
        rules = extract_rules(
            samples, decision_key="k", min_coverage=20, min_precision=0.95, max_depth=3,
        )
        self.assertTrue(rules)
        rule = rules[0]
        self.assertEqual(rule.decision_key, "k")
        self.assertEqual(rule.precision, 1.0)
        self.assertEqual(rule.support_total, 60)
        # The single positive predicate is flag==True → 'a'.
        self.assertEqual(rule.chosen, "a")
        self.assertEqual([(p.feature, p.value) for p in rule.predicate], [("flag", True)])

    def test_low_precision_leaf_excluded(self) -> None:
        # Noisy: flag=True is 50/50 a/b → never reaches min_precision.
        samples = (
            [Sample({"flag": True}, "a") for _ in range(15)]
            + [Sample({"flag": True}, "b") for _ in range(15)]
        )
        rules = extract_rules(samples, decision_key="k", min_coverage=10, min_precision=0.95)
        self.assertEqual(rules, [])

    def test_min_coverage_excludes_small_leaves(self) -> None:
        samples = (
            [Sample({"flag": True}, "a") for _ in range(5)]
            + [Sample({"flag": False}, "b") for _ in range(5)]
        )
        # Require 20 coverage but only 5 each → nothing qualifies.
        rules = extract_rules(samples, decision_key="k", min_coverage=20)
        self.assertEqual(rules, [])


# ---------------------------------------------------------------------------
# Backtest metrics — pure, list[str] only
# ---------------------------------------------------------------------------


class DominantChoiceTestCase(unittest.TestCase):
    def test_dominant_choice_majority(self) -> None:
        winner, share = dominant_choice(["a", "a", "b"])
        self.assertEqual(winner, "a")
        self.assertAlmostEqual(share, 2 / 3)

    def test_dominant_choice_tie_broken_alphabetically(self) -> None:
        winner, share = dominant_choice(["b", "a"])
        self.assertEqual(winner, "a")
        self.assertEqual(share, 0.5)


class BacktestMetricsTestCase(unittest.TestCase):
    def test_not_enough_data(self) -> None:
        m = compute_backtest_metrics("k", ["a"], min_history=3, min_confidence=1.0)
        self.assertEqual(m["error"], "not_enough_data")
        self.assertEqual(m["total_observations"], 1)

    def test_perfect_sequence_is_promote_ready(self) -> None:
        choices = ["a"] * 10
        m = compute_backtest_metrics("k", choices, min_history=3, min_confidence=1.0)
        self.assertEqual(m["candidate_choice"], "a")
        self.assertEqual(m["accuracy"], 1.0)
        self.assertTrue(m["promote_ready"])
        # idx 0,1,2 abstain (history < min_history), 3..9 predict → 7 predictions.
        self.assertEqual(m["predictions"], 7)
        self.assertEqual(m["abstentions"], 3)

    def test_confidence_gate_forces_abstention(self) -> None:
        # After enough mixed history the dominant share stays below 1.0, so a
        # min_confidence of 1.0 forces abstention once both classes are seen.
        # With min_history=2, every prediction window holds both 'a' and 'b'
        # → confidence < 1.0 → all abstain, zero predictions.
        choices = ["a", "b"] * 5
        m = compute_backtest_metrics("k", choices, min_history=2, min_confidence=1.0)
        self.assertEqual(m["predictions"], 0)
        self.assertEqual(m["accuracy"], 0.0)
        self.assertFalse(m["promote_ready"])

    def test_imperfect_accuracy_not_promote_ready(self) -> None:
        # Mostly 'a' with one 'b' at the end → a wrong prediction.
        choices = ["a"] * 9 + ["b"]
        m = compute_backtest_metrics("k", choices, min_history=3, min_confidence=0.5)
        self.assertLess(m["accuracy"], 1.0)
        self.assertFalse(m["promote_ready"])


# ---------------------------------------------------------------------------
# Deterministic rule matching — pure (no storage/loading)
# ---------------------------------------------------------------------------


class PredicateMatchesTestCase(unittest.TestCase):
    def test_empty_predicate_always_matches(self) -> None:
        self.assertTrue(predicate_matches([], {"x": True}))

    def test_single_clause_match(self) -> None:
        pred = [{"feature": "is_root", "op": "==", "value": True}]
        self.assertTrue(predicate_matches(pred, {"is_root": True}))
        self.assertFalse(predicate_matches(pred, {"is_root": False}))
        self.assertFalse(predicate_matches(pred, {}))

    def test_conjunction_requires_all_clauses(self) -> None:
        pred = [
            {"feature": "is_root", "op": "==", "value": True},
            {"feature": "has_mention", "op": "==", "value": True},
        ]
        self.assertTrue(predicate_matches(pred, {"is_root": True, "has_mention": True}))
        self.assertFalse(predicate_matches(pred, {"is_root": True, "has_mention": False}))

    def test_unknown_op_rejected(self) -> None:
        self.assertFalse(predicate_matches([{"feature": "x", "op": "!=", "value": 1}], {"x": 2}))

    def test_malformed_predicate_rejected(self) -> None:
        self.assertFalse(predicate_matches([{"not_a_clause": True}], {"x": 1}))
        self.assertFalse(predicate_matches("not_a_list", {"x": 1}))  # type: ignore[arg-type]


class MatchRuleTestCase(unittest.TestCase):
    def test_sort_by_specificity_longest_first(self) -> None:
        short = ([{"feature": "a", "op": "==", "value": 1}], "short")
        long = (
            [
                {"feature": "a", "op": "==", "value": 1},
                {"feature": "b", "op": "==", "value": 2},
            ],
            "long",
        )
        ordered = sort_rules_by_specificity([short, long])
        self.assertEqual([p[1] for p in ordered], ["long", "short"])

    def test_match_rule_most_specific_wins(self) -> None:
        rules = [
            ([{"feature": "is_root", "op": "==", "value": True}], "public"),
            (
                [
                    {"feature": "is_root", "op": "==", "value": True},
                    {"feature": "has_mention", "op": "==", "value": True},
                ],
                "feedback",
            ),
        ]
        self.assertEqual(
            match_rule(rules, {"is_root": True, "has_mention": True}), "feedback",
        )

    def test_match_rule_falls_back_to_less_specific(self) -> None:
        rules = [
            ([{"feature": "is_root", "op": "==", "value": True}], "public"),
            (
                [
                    {"feature": "is_root", "op": "==", "value": True},
                    {"feature": "has_mention", "op": "==", "value": True},
                ],
                "feedback",
            ),
        ]
        # has_mention=False → long rule misses, short still matches.
        self.assertEqual(
            match_rule(rules, {"is_root": True, "has_mention": False}), "public",
        )

    def test_match_rule_none_when_no_match(self) -> None:
        rules = [([{"feature": "x", "op": "==", "value": 1}], "X")]
        self.assertIsNone(match_rule(rules, {"x": 2}))

    def test_match_rule_empty_predicate_matches_anything(self) -> None:
        rules = [([], "default")]
        self.assertEqual(match_rule(rules, {"anything": 1}), "default")


if __name__ == "__main__":
    unittest.main()
