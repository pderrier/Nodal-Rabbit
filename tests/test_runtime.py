"""Tests for the AgentOS runtime SDK (Phase D)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agentos.runtime import _predicate_matches, check_rule
from agentos.storage import (
    db_path,
    ensure_schema,
    list_promoted_feature_rules,
    record_promoted_feature_rule,
)


class PredicateMatchesTestCase(unittest.TestCase):
    def test_empty_predicate_always_matches(self) -> None:
        self.assertTrue(_predicate_matches([], {"x": True}))

    def test_single_clause_match(self) -> None:
        pred = [{"feature": "is_root", "op": "==", "value": True}]
        self.assertTrue(_predicate_matches(pred, {"is_root": True}))
        self.assertFalse(_predicate_matches(pred, {"is_root": False}))
        self.assertFalse(_predicate_matches(pred, {}))

    def test_conjunction_requires_all_clauses(self) -> None:
        pred = [
            {"feature": "is_root", "op": "==", "value": True},
            {"feature": "has_mention", "op": "==", "value": True},
        ]
        self.assertTrue(_predicate_matches(pred, {"is_root": True, "has_mention": True}))
        self.assertFalse(_predicate_matches(pred, {"is_root": True, "has_mention": False}))
        self.assertFalse(_predicate_matches(pred, {"is_root": False, "has_mention": True}))

    def test_unknown_op_rejected_conservatively(self) -> None:
        pred = [{"feature": "x", "op": "!=", "value": 1}]
        self.assertFalse(_predicate_matches(pred, {"x": 2}))

    def test_malformed_predicate_rejected(self) -> None:
        self.assertFalse(_predicate_matches([{"not_a_clause": True}], {"x": 1}))
        self.assertFalse(_predicate_matches("not_a_list", {"x": 1}))  # type: ignore[arg-type]


class CheckRuleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.conn = ensure_schema(self.home)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_returns_none_when_no_rules_promoted(self) -> None:
        result = check_rule("teams.classify_thread", {"is_root": True}, conn=self.conn)
        self.assertIsNone(result)

    def test_returns_none_when_no_db_exists(self) -> None:
        # Point at a fresh, empty home (no DB file at all).
        with tempfile.TemporaryDirectory() as fresh:
            result = check_rule("k", {"x": 1}, agentos_home=fresh)
            self.assertIsNone(result)

    def test_matches_simple_rule(self) -> None:
        record_promoted_feature_rule(
            self.conn,
            rule_id="rule_1",
            decision_key="teams.classify_thread",
            predicate=[
                {"feature": "is_root", "op": "==", "value": True},
                {"feature": "has_mention", "op": "==", "value": True},
            ],
            chosen="feedback",
            metrics={"coverage": 47, "precision": 1.0},
        )
        result = check_rule(
            "teams.classify_thread",
            {"is_root": True, "has_mention": True, "extra": "ignored"},
            conn=self.conn,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["chosen"], "feedback")
        self.assertEqual(result["rule_id"], "rule_1")
        self.assertTrue(result["fallback_enabled"])

    def test_no_match_when_predicate_unsatisfied(self) -> None:
        record_promoted_feature_rule(
            self.conn,
            rule_id="rule_1",
            decision_key="k",
            predicate=[{"feature": "is_root", "op": "==", "value": True}],
            chosen="feedback",
            metrics={},
        )
        # Feature value differs.
        self.assertIsNone(check_rule("k", {"is_root": False}, conn=self.conn))
        # Feature absent entirely.
        self.assertIsNone(check_rule("k", {}, conn=self.conn))

    def test_more_specific_rule_wins(self) -> None:
        # Two rules for the same key: a 1-clause rule and a 2-clause rule.
        # The 2-clause one (more specific) should win when both match.
        record_promoted_feature_rule(
            self.conn,
            rule_id="r_short",
            decision_key="k",
            predicate=[{"feature": "is_root", "op": "==", "value": True}],
            chosen="public",
            metrics={},
        )
        record_promoted_feature_rule(
            self.conn,
            rule_id="r_long",
            decision_key="k",
            predicate=[
                {"feature": "is_root", "op": "==", "value": True},
                {"feature": "has_mention", "op": "==", "value": True},
            ],
            chosen="feedback",
            metrics={},
        )
        result = check_rule("k", {"is_root": True, "has_mention": True}, conn=self.conn)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["rule_id"], "r_long")
        self.assertEqual(result["chosen"], "feedback")

    def test_falls_back_to_less_specific_when_more_specific_misses(self) -> None:
        record_promoted_feature_rule(
            self.conn,
            rule_id="r_short",
            decision_key="k",
            predicate=[{"feature": "is_root", "op": "==", "value": True}],
            chosen="public",
            metrics={},
        )
        record_promoted_feature_rule(
            self.conn,
            rule_id="r_long",
            decision_key="k",
            predicate=[
                {"feature": "is_root", "op": "==", "value": True},
                {"feature": "has_mention", "op": "==", "value": True},
            ],
            chosen="feedback",
            metrics={},
        )
        # Long rule fails (has_mention=False), short rule still matches.
        result = check_rule("k", {"is_root": True, "has_mention": False}, conn=self.conn)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["rule_id"], "r_short")

    def test_only_promoted_rules_considered(self) -> None:
        # Insert directly with status='rejected' — must NOT match.
        self.conn.execute(
            """
            INSERT INTO promoted_rules(
                rule_id, decision_key, candidate_choice, status, fallback_enabled,
                metrics_json, promoted_at, predicate_json
            ) VALUES ('rejected_rule', 'k', 'x', 'rejected', 1, '{}', '2026-01-01T00:00:00Z',
                      '[{"feature":"is_root","op":"==","value":true}]')
            """
        )
        self.conn.commit()
        self.assertIsNone(check_rule("k", {"is_root": True}, conn=self.conn))

    def test_decision_key_isolation(self) -> None:
        record_promoted_feature_rule(
            self.conn,
            rule_id="r_a",
            decision_key="key.a",
            predicate=[{"feature": "x", "op": "==", "value": 1}],
            chosen="A",
            metrics={},
        )
        # Looking up under a different decision_key must miss.
        self.assertIsNone(check_rule("key.b", {"x": 1}, conn=self.conn))
        # Same decision_key with matching features: hit.
        result = check_rule("key.a", {"x": 1}, conn=self.conn)
        self.assertIsNotNone(result)


class StorageMigrationTestCase(unittest.TestCase):
    """Confirm the predicate_json column is added idempotently to existing DBs."""

    def test_migration_is_idempotent_on_existing_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            # First call creates the schema with predicate_json column.
            conn1 = ensure_schema(home)
            cols = {row[1] for row in conn1.execute("PRAGMA table_info(promoted_rules)")}
            self.assertIn("predicate_json", cols)
            conn1.close()
            # Second call on same DB must be a no-op (idempotent).
            conn2 = ensure_schema(home)
            cols2 = {row[1] for row in conn2.execute("PRAGMA table_info(promoted_rules)")}
            self.assertEqual(cols, cols2)
            conn2.close()

    def test_migration_on_pre_existing_db_without_column(self) -> None:
        """Simulate an older DB created before predicate_json existed."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            home.mkdir(exist_ok=True)
            conn = sqlite3.connect(db_path(home))
            # Manually create the OLD schema (no predicate_json column).
            conn.execute(
                """
                CREATE TABLE promoted_rules (
                    rule_id TEXT PRIMARY KEY,
                    decision_key TEXT NOT NULL,
                    candidate_choice TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fallback_enabled INTEGER NOT NULL,
                    metrics_json TEXT NOT NULL,
                    promoted_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            conn.close()
            # Now run ensure_schema — must add the missing column without errors.
            conn2 = ensure_schema(home)
            cols = {row[1] for row in conn2.execute("PRAGMA table_info(promoted_rules)")}
            self.assertIn("predicate_json", cols)
            conn2.close()


if __name__ == "__main__":
    unittest.main()
