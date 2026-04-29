from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentos.storage import (
    PromotedRuleRecord,
    RunRecord,
    append_trace,
    create_run_id,
    ensure_schema,
    get_decision,
    get_run,
    list_decision_choices,
    list_decisions,
    list_decision_patterns,
    list_decision_patterns_by_features,
    list_promoted_rules,
    list_runs,
    record_decision,
    record_event,
    record_outcome,
    record_promoted_rule,
    record_run,
    utc_now_iso,
)


class StorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.conn = ensure_schema(self.home)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_schema_initialization_creates_expected_tables(self) -> None:
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {row[0] for row in cursor.fetchall()}
        self.assertTrue(
            {"runs", "events", "decisions", "outcomes", "promoted_rules"}.issubset(names)
        )

    def test_record_and_fetch_run(self) -> None:
        run = RunRecord(
            run_id="run_abc",
            intent="demo.intent",
            source="tests",
            command="echo hi",
            started_at="2026-01-01T00:00:00.000Z",
            finished_at="2026-01-01T00:00:01.000Z",
            exit_code=0,
            duration_ms=1000,
            trace_path=".agentos/runs/run_abc/trace.jsonl",
        )
        record_run(self.conn, run)
        found = get_run(self.conn, "run_abc")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["intent"], "demo.intent")

    def test_record_event_decision_outcome(self) -> None:
        record_run(
            self.conn,
            RunRecord(
                run_id="run_evt",
                intent="intent",
                source="tests",
                command="echo",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.100Z",
                exit_code=0,
                duration_ms=100,
                trace_path="trace",
            ),
        )
        record_event(self.conn, "run_evt", "env_snapshot", {"safe": True})
        decision_id = record_decision(
            self.conn,
            "run_evt",
            "route",
            {"chosen": "retry"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        outcome_id = record_outcome(self.conn, "run_evt", "success", {"result": "green"})

        decision = get_decision(self.conn, decision_id)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision["decision_key"], "route")

        decisions = list_decisions(self.conn, limit=10)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["id"], decision_id)

        out_cursor = self.conn.execute("SELECT id, status FROM outcomes WHERE id = ?", (outcome_id,))
        out = out_cursor.fetchone()
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out[1], "success")

    def test_trace_append_and_run_listing(self) -> None:
        run_id = create_run_id()
        append_trace(self.home, run_id, "run_started", {"intent": "demo"})
        path = self.home / "runs" / run_id / "trace.jsonl"
        self.assertTrue(path.exists())

        record_run(
            self.conn,
            RunRecord(
                run_id=run_id,
                intent="demo.intent",
                source="tests",
                command="echo ok",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.010Z",
                exit_code=0,
                duration_ms=10,
                trace_path=str(path),
            ),
        )
        runs = list_runs(self.conn, limit=5)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_id"], run_id)

    def test_list_decision_patterns_returns_dominant_choice_metrics(self) -> None:
        record_run(
            self.conn,
            RunRecord(
                run_id="run_patterns",
                intent="demo.patterns",
                source="tests",
                command="echo patterns",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.010Z",
                exit_code=0,
                duration_ms=10,
                trace_path="trace",
            ),
        )
        record_decision(
            self.conn,
            "run_patterns",
            "route.fix_ci",
            {"chosen": "retry"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_decision(
            self.conn,
            "run_patterns",
            "route.fix_ci",
            {"chosen": "retry"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_decision(
            self.conn,
            "run_patterns",
            "route.fix_ci",
            {"chosen": "escalate"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_decision(
            self.conn,
            "run_patterns",
            "route.docs",
            {"chosen": "delegate"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_decision(
            self.conn,
            "run_patterns",
            "route.docs",
            {"chosen": "delegate"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_outcome(self.conn, "run_patterns", "success", {"result": "green"})

        rows = list_decision_patterns(self.conn, min_support=2, limit=10)
        self.assertEqual(len(rows), 2)
        by_key = {row["decision_key"]: row for row in rows}

        self.assertEqual(by_key["route.fix_ci"]["dominant_choice"], "retry")
        self.assertEqual(by_key["route.fix_ci"]["dominant_count"], 2)
        self.assertEqual(by_key["route.fix_ci"]["support"], 3)
        self.assertAlmostEqual(float(by_key["route.fix_ci"]["confidence"]), 2 / 3, places=6)

        self.assertEqual(by_key["route.docs"]["dominant_choice"], "delegate")
        self.assertEqual(by_key["route.docs"]["dominant_count"], 2)
        self.assertEqual(by_key["route.docs"]["support"], 2)
        self.assertAlmostEqual(float(by_key["route.docs"]["confidence"]), 1.0, places=6)

    def test_list_decision_choices_keeps_order_and_filters_nulls(self) -> None:
        record_run(
            self.conn,
            RunRecord(
                run_id="run_choices",
                intent="demo.choices",
                source="tests",
                command="echo choices",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.010Z",
                exit_code=0,
                duration_ms=10,
                trace_path="trace",
            ),
        )
        record_decision(
            self.conn,
            "run_choices",
            "route.fix_ci",
            {"chosen": "retry"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_decision(
            self.conn,
            "run_choices",
            "route.fix_ci",
            {"note": "missing chosen"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_decision(
            self.conn,
            "run_choices",
            "route.fix_ci",
            {"chosen": "escalate"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_decision(
            self.conn,
            "run_choices",
            "route.docs",
            {"chosen": "delegate"},
            decision_source="cli_record",
            decision_validity="valid",
            compilation_candidate=True,
        )
        record_outcome(self.conn, "run_choices", "success", {"result": "green"})

        choices = list_decision_choices(self.conn, decision_key="route.fix_ci")
        self.assertEqual(choices, ["retry", "escalate"])

    def test_record_and_list_promoted_rules(self) -> None:
        record_promoted_rule(
            self.conn,
            PromotedRuleRecord(
                rule_id="rule_123",
                decision_key="route.fix_ci",
                candidate_choice="retry",
                status="promoted",
                fallback_enabled=True,
                metrics_json='{"accuracy": 1.0, "predictions": 4}',
                promoted_at=utc_now_iso(),
            ),
        )

        rows = list_promoted_rules(self.conn, limit=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rule_id"], "rule_123")
        self.assertEqual(rows[0]["decision_key"], "route.fix_ci")
        self.assertEqual(rows[0]["candidate_choice"], "retry")
        self.assertEqual(rows[0]["status"], "promoted")
        self.assertEqual(rows[0]["fallback_enabled"], 1)

    def _seed_run(self, run_id: str) -> None:
        record_run(
            self.conn,
            RunRecord(
                run_id=run_id,
                intent="demo.features",
                source="tests",
                command="echo features",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.010Z",
                exit_code=0,
                duration_ms=10,
                trace_path="trace",
            ),
        )
        record_outcome(self.conn, run_id, "success", {"result": "green"})

    def _seed_decision(self, run_id: str, key: str, payload: dict) -> None:
        record_decision(
            self.conn,
            run_id,
            key,
            payload,
            decision_source="decision_file",
            decision_validity="valid",
            compilation_candidate=True,
        )

    def test_list_decision_patterns_by_features_groups_by_feature_signature(self) -> None:
        # Two distinct feature buckets for the same decision_key — the miner
        # must report each as a separate row with its own dominant choice.
        for run_id in ("run_a", "run_b", "run_c"):
            self._seed_run(run_id)
        # Bucket 1: {is_root: true, has_mention: true} → always feedback
        self._seed_decision("run_a", "teams.classify_thread", {
            "chosen": "feedback",
            "features": {"is_root": True, "has_mention": True},
        })
        self._seed_decision("run_a", "teams.classify_thread", {
            "chosen": "feedback",
            "features": {"is_root": True, "has_mention": True},
        })
        self._seed_decision("run_b", "teams.classify_thread", {
            "chosen": "feedback",
            "features": {"is_root": True, "has_mention": True},
        })
        # Bucket 2: {is_root: false, has_mention: false} → always skip
        self._seed_decision("run_b", "teams.classify_thread", {
            "chosen": "skip",
            "features": {"is_root": False, "has_mention": False},
        })
        self._seed_decision("run_c", "teams.classify_thread", {
            "chosen": "skip",
            "features": {"is_root": False, "has_mention": False},
        })

        rows = list_decision_patterns_by_features(self.conn, min_support=2)
        self.assertEqual(len(rows), 2)
        by_choice = {r["dominant_choice"]: r for r in rows}
        self.assertIn("feedback", by_choice)
        self.assertIn("skip", by_choice)
        self.assertEqual(by_choice["feedback"]["support"], 3)
        self.assertEqual(by_choice["feedback"]["confidence"], 1.0)
        self.assertEqual(by_choice["feedback"]["features"], {"is_root": True, "has_mention": True})
        self.assertEqual(by_choice["skip"]["support"], 2)
        self.assertEqual(by_choice["skip"]["confidence"], 1.0)

    def test_list_decision_patterns_by_features_skips_decisions_without_features(self) -> None:
        self._seed_run("run_x")
        # No features field — should be skipped (handled by list_decision_patterns)
        self._seed_decision("run_x", "route.fix_ci", {"chosen": "retry"})
        self._seed_decision("run_x", "route.fix_ci", {"chosen": "retry"})
        rows = list_decision_patterns_by_features(self.conn, min_support=2)
        self.assertEqual(rows, [])

    def test_list_decision_patterns_by_features_filters_by_decision_key(self) -> None:
        self._seed_run("run_y")
        self._seed_decision("run_y", "key.a", {"chosen": "x", "features": {"f": 1}})
        self._seed_decision("run_y", "key.a", {"chosen": "x", "features": {"f": 1}})
        self._seed_decision("run_y", "key.b", {"chosen": "y", "features": {"g": 2}})
        self._seed_decision("run_y", "key.b", {"chosen": "y", "features": {"g": 2}})
        rows = list_decision_patterns_by_features(self.conn, decision_key="key.a")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision_key"], "key.a")

    def test_list_decision_patterns_by_features_canonicalizes_key_order(self) -> None:
        # Two decisions with identical features but different key insertion
        # order must end up in the same bucket.
        self._seed_run("run_z")
        self._seed_decision("run_z", "k", {"chosen": "ok", "features": {"a": 1, "b": 2}})
        self._seed_decision("run_z", "k", {"chosen": "ok", "features": {"b": 2, "a": 1}})
        rows = list_decision_patterns_by_features(self.conn, min_support=2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["support"], 2)

    def test_list_decision_patterns_by_features_requires_confirmed_outcome(self) -> None:
        # Decision with NO outcome must be excluded.
        record_run(
            self.conn,
            RunRecord(
                run_id="run_no_outcome",
                intent="x",
                source="t",
                command="c",
                started_at="2026-01-01T00:00:00.000Z",
                finished_at="2026-01-01T00:00:00.010Z",
                exit_code=0,
                duration_ms=10,
                trace_path="t",
            ),
        )
        self._seed_decision("run_no_outcome", "k", {"chosen": "x", "features": {"f": 1}})
        self._seed_decision("run_no_outcome", "k", {"chosen": "x", "features": {"f": 1}})
        rows = list_decision_patterns_by_features(self.conn, min_support=2)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
