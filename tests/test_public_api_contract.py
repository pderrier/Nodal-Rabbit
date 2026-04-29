"""Public API contract tests.

These tests lock the *consumer-facing* surface of AgentOS so that
unrelated refactors can't silently break downstream wrappers
(e.g. claude-alert-analyzer's TeamsActionClassifier, which imports
``agentos.runtime.check_rule`` and depends on its return shape).

If you change anything tested here, you are making a *breaking* change
to the public API and must coordinate with consumers and bump a major
version. Otherwise: these tests must keep passing untouched.

Surface covered:
1. ``from agentos.runtime import check_rule`` — symbol exists at this path.
2. ``check_rule(decision_key, features, *, agentos_home=None, conn=None)``
   — keyword-only kwargs, accepted positional args, return shape.
3. Decision-payload schema accepts ``features`` field with primitive values.
4. CLI surface: ``agentos rules promote-extracted`` accepts the documented
   flags and produces a JSON line with the documented keys.
5. ``agentos.storage.list_promoted_feature_rules`` exists and returns rows
   with the documented columns.
"""
from __future__ import annotations

import inspect
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentos.cli import main as cli_main


class RuntimeCheckRuleContractTestCase(unittest.TestCase):
    """The runtime SDK's public function signature and return shape."""

    def test_check_rule_is_importable_at_documented_path(self) -> None:
        # The documented import — DO NOT change without bumping major version.
        from agentos.runtime import check_rule  # noqa: F401

    def test_check_rule_signature_matches_contract(self) -> None:
        from agentos.runtime import check_rule

        sig = inspect.signature(check_rule)
        params = sig.parameters
        # Positional-or-keyword: decision_key, features.
        self.assertIn("decision_key", params)
        self.assertIn("features", params)
        # Keyword-only: agentos_home, conn (both optional, default None).
        self.assertIn("agentos_home", params)
        self.assertIn("conn", params)
        self.assertEqual(params["agentos_home"].default, None)
        self.assertEqual(params["conn"].default, None)
        # agentos_home and conn must be keyword-only — passing them
        # positionally is NOT part of the contract.
        self.assertEqual(params["agentos_home"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(params["conn"].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_check_rule_returns_none_when_no_db(self) -> None:
        from agentos.runtime import check_rule

        with tempfile.TemporaryDirectory() as tmp:
            # No DB exists in this fresh home → must return None, not raise.
            result = check_rule("k", {"x": 1}, agentos_home=tmp)
            self.assertIsNone(result)

    def test_check_rule_match_returns_documented_keys(self) -> None:
        from agentos.runtime import check_rule
        from agentos.storage import (
            ensure_schema,
            record_promoted_feature_rule,
        )

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            conn = ensure_schema(home)
            record_promoted_feature_rule(
                conn,
                rule_id="r1",
                decision_key="teams.classify_thread",
                predicate=[{"feature": "is_root", "op": "==", "value": True}],
                chosen="feedback",
                metrics={"coverage": 50, "precision": 1.0},
            )
            result = check_rule(
                "teams.classify_thread", {"is_root": True}, conn=conn,
            )
            self.assertIsNotNone(result)
            assert result is not None
            # Documented keys — consumers depend on these by NAME.
            self.assertIn("chosen", result)
            self.assertIn("rule_id", result)
            self.assertIn("predicate", result)
            self.assertIn("fallback_enabled", result)
            # Documented value types.
            self.assertIsInstance(result["chosen"], str)
            self.assertIsInstance(result["rule_id"], str)
            self.assertIsInstance(result["predicate"], list)
            self.assertIsInstance(result["fallback_enabled"], bool)
            conn.close()


class DecisionPayloadFeaturesContractTestCase(unittest.TestCase):
    """The decision-payload schema's `features` field — what consumers emit."""

    def test_features_field_with_primitives_is_valid(self) -> None:
        from agentos.cli import _validate_declared_decision

        payload = {
            "step_id": "teams.classify_thread",
            "decision_type": "llm",
            "input_fingerprint": "abc",
            "output": {"chosen": "feedback", "confidence": 0.95},
            "evidence": [],
            "features": {
                "is_root": True,
                "has_mention": False,
                "channel": "devops",
                "count": 7,
                "ratio": 0.5,
            },
            "compilation_candidate": True,
        }
        self.assertEqual(_validate_declared_decision(payload), "valid")

    def test_features_field_with_nested_value_rejected(self) -> None:
        """Consumers MUST be told their nested-value rules don't validate
        — emitting a dict-as-value would silently turn into invalid_schema
        and the decision would be excluded from mining."""
        from agentos.cli import _validate_declared_decision

        payload = {
            "step_id": "k",
            "decision_type": "llm",
            "input_fingerprint": "abc",
            "output": {"chosen": "x"},
            "evidence": [],
            "features": {"nested": {"oops": 1}},
            "compilation_candidate": True,
        }
        self.assertEqual(_validate_declared_decision(payload), "invalid_schema")

    def test_features_field_is_optional(self) -> None:
        """A decision without features must STILL validate — the field is opt-in."""
        from agentos.cli import _validate_declared_decision

        payload = {
            "step_id": "k",
            "decision_type": "llm",
            "input_fingerprint": "abc",
            "output": {"chosen": "x"},
            "evidence": [],
            "compilation_candidate": True,
        }
        self.assertEqual(_validate_declared_decision(payload), "valid")


class StorageContractTestCase(unittest.TestCase):
    """Storage-layer functions consumers may call directly."""

    def test_list_promoted_feature_rules_returns_documented_columns(self) -> None:
        from agentos.storage import (
            ensure_schema,
            list_promoted_feature_rules,
            record_promoted_feature_rule,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn = ensure_schema(Path(tmp))
            record_promoted_feature_rule(
                conn, rule_id="r1", decision_key="k",
                predicate=[{"feature": "x", "op": "==", "value": 1}],
                chosen="y", metrics={"coverage": 5},
            )
            rows = list_promoted_feature_rules(conn, "k")
            self.assertEqual(len(rows), 1)
            row = rows[0]
            # Documented columns — consumers depend on these by NAME.
            for col in (
                "rule_id", "decision_key", "candidate_choice", "status",
                "fallback_enabled", "metrics_json", "promoted_at", "predicate_json",
            ):
                # sqlite3.Row.keys() returns a list of column names.
                self.assertIn(col, row.keys())
            conn.close()

    def test_record_promoted_feature_rule_signature_matches_contract(self) -> None:
        """Keyword arguments expected by callers (esp. alert_brain)."""
        from agentos.storage import record_promoted_feature_rule

        sig = inspect.signature(record_promoted_feature_rule)
        for required in ("rule_id", "decision_key", "predicate", "chosen", "metrics"):
            self.assertIn(required, sig.parameters)


class PythonVersionContractTestCase(unittest.TestCase):
    """Lock the minimum Python version we promise to support.

    pyproject.toml says ``requires-python = ">=3.10"`` — every public module
    must therefore be importable on 3.10 too. Imports that depend on
    later-version features (e.g. ``from datetime import UTC``, added in 3.11)
    have caused silent test-skips for downstream consumers and must be
    rejected.
    """

    def test_storage_imports_no_python_3_11_only_symbols(self) -> None:
        # If you're tempted to add Python 3.11+ syntax/imports to storage.py,
        # bump pyproject.toml's requires-python first AND coordinate with
        # consumers (alert_brain runs on Python 3.10 in production).
        src = (Path(__file__).parent.parent / "src" / "agentos" / "storage.py").read_text()
        forbidden = [
            ("from datetime import UTC", "3.11+ — use `datetime.timezone.utc` instead"),
            ("from datetime import.*UTC", "3.11+ — use `datetime.timezone.utc` instead"),
        ]
        import re
        for pattern, hint in forbidden:
            self.assertFalse(
                re.search(pattern, src),
                f"agentos/storage.py contains a Python 3.11+ symbol "
                f"({pattern}) but pyproject.toml claims 3.10 support. {hint}",
            )

    def test_pyproject_requires_python_matches_minimum_supported(self) -> None:
        # Lock the declared minimum so tightening it is an explicit decision.
        pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text()
        self.assertIn('requires-python = ">=3.10"', pyproject)


class CLIContractTestCase(unittest.TestCase):
    """CLI commands consumers may invoke from wrapper scripts."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("AGENTOS_HOME")
        os.environ["AGENTOS_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("AGENTOS_HOME", None)
        else:
            os.environ["AGENTOS_HOME"] = self._old_home
        self._tmp.cleanup()

    def _run(self, argv: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(argv)
        return code, out.getvalue()

    def test_rules_promote_extracted_accepts_documented_flags(self) -> None:
        """All flags consumers script against must remain accepted."""
        code, out = self._run([
            "rules", "promote-extracted",
            "--decision-key", "teams.classify_thread",
            "--predicate-json", '[{"feature":"is_root","op":"==","value":true}]',
            "--chosen", "feedback",
            "--metrics-json", '{"coverage":50,"precision":1.0}',
        ])
        self.assertEqual(code, 0, f"unexpected exit: {code}, output: {out!r}")
        result = json.loads(out)
        # Documented output keys.
        for key in ("rule_id", "decision_key", "chosen", "predicate", "fallback_enabled", "status"):
            self.assertIn(key, result, f"missing key {key} in CLI output")

    def test_decision_record_accepts_features_json_flag(self) -> None:
        """The --features-json flag is part of the public CLI."""
        code, out = self._run([
            "wrap", "--intent", "demo", "--", "python", "-c", "print('ok')",
        ])
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        code, out = self._run([
            "decision", "record", "--run-id", run_id,
            "--key", "k", "--step", "k", "--type", "llm",
            "--input-fingerprint", "fp",
            "--output-json", '{"chosen":"x"}',
            "--evidence-json", "[]", "--candidate", "true",
            "--features-json", '{"is_root": true}',
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision_validity"], "valid")

    def test_patterns_list_accepts_by_features_flag(self) -> None:
        """The --by-features flag is part of the public CLI."""
        # Empty store is fine — flag must just be accepted, not produce an error.
        code, _ = self._run(["patterns", "list", "--by-features"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
