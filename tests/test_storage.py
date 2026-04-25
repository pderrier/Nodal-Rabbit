from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentos.storage import (
    RunRecord,
    append_trace,
    create_run_id,
    ensure_schema,
    get_decision,
    get_run,
    list_decisions,
    list_runs,
    record_decision,
    record_event,
    record_outcome,
    record_run,
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
        self.assertTrue({"runs", "events", "decisions", "outcomes"}.issubset(names))

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


if __name__ == "__main__":
    unittest.main()
