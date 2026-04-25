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
        decision_id = record_decision(self.conn, "run_evt", "route", {"chosen": "retry"})
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
        record_decision(self.conn, "run_patterns", "route.fix_ci", {"chosen": "retry"})
        record_decision(self.conn, "run_patterns", "route.fix_ci", {"chosen": "retry"})
        record_decision(self.conn, "run_patterns", "route.fix_ci", {"chosen": "escalate"})
        record_decision(self.conn, "run_patterns", "route.docs", {"chosen": "delegate"})
        record_decision(self.conn, "run_patterns", "route.docs", {"chosen": "delegate"})

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
        record_decision(self.conn, "run_choices", "route.fix_ci", {"chosen": "retry"})
        record_decision(self.conn, "run_choices", "route.fix_ci", {"note": "missing chosen"})
        record_decision(self.conn, "run_choices", "route.fix_ci", {"chosen": "escalate"})
        record_decision(self.conn, "run_choices", "route.docs", {"chosen": "delegate"})

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


if __name__ == "__main__":
    unittest.main()
