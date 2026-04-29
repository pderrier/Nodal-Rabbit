from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

from agentos.cli import _load_json_payload, _resolve_run_id, main, parse_args


class CLITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("AGENTOS_HOME")
        os.environ["AGENTOS_HOME"] = self.temp_dir.name

    def tearDown(self) -> None:
        if self.old_home is None:
            os.environ.pop("AGENTOS_HOME", None)
        else:
            os.environ["AGENTOS_HOME"] = self.old_home
        os.environ.pop("AGENTOS_RUN_ID", None)
        self.temp_dir.cleanup()

    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_parse_args_wrap(self) -> None:
        args = parse_args(["wrap", "--intent", "demo", "--", "echo", "ok"])
        self.assertEqual(args.command, "wrap")
        self.assertEqual(args.intent, "demo")
        self.assertEqual(args.cmd[-2:], ["echo", "ok"])

    def test_parse_args_patterns_list(self) -> None:
        args = parse_args(["patterns", "list", "--min-support", "3", "--limit", "10"])
        self.assertEqual(args.command, "patterns")
        self.assertEqual(args.patterns_command, "list")
        self.assertEqual(args.min_support, 3)
        self.assertEqual(args.limit, 10)

    def test_parse_args_backtest_run(self) -> None:
        args = parse_args(
            [
                "backtest",
                "run",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "4",
                "--min-confidence",
                "0.75",
            ]
        )
        self.assertEqual(args.command, "backtest")
        self.assertEqual(args.backtest_command, "run")
        self.assertEqual(args.decision_key, "route.fix_ci")
        self.assertEqual(args.min_history, 4)
        self.assertEqual(args.min_confidence, 0.75)

    def test_parse_args_compile_aliases(self) -> None:
        args = parse_args(["compile", "candidates", "--min-support", "3", "--limit", "10"])
        self.assertEqual(args.command, "compile")
        self.assertEqual(args.compile_command, "candidates")
        self.assertEqual(args.min_support, 3)
        self.assertEqual(args.limit, 10)

        args = parse_args(
            [
                "compile",
                "backtest",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "4",
                "--min-confidence",
                "0.75",
            ]
        )
        self.assertEqual(args.command, "compile")
        self.assertEqual(args.compile_command, "backtest")
        self.assertEqual(args.decision_key, "route.fix_ci")
        self.assertEqual(args.min_history, 4)
        self.assertEqual(args.min_confidence, 0.75)

        args = parse_args(
            [
                "compile",
                "promote",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "4",
                "--min-confidence",
                "0.8",
                "--min-accuracy",
                "0.9",
            ]
        )
        self.assertEqual(args.command, "compile")
        self.assertEqual(args.compile_command, "promote")
        self.assertEqual(args.decision_key, "route.fix_ci")
        self.assertEqual(args.min_history, 4)
        self.assertEqual(args.min_confidence, 0.8)
        self.assertEqual(args.min_accuracy, 0.9)

        args = parse_args(
            [
                "compile",
                "reject",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "4",
                "--min-confidence",
                "0.8",
                "--reason",
                "manual_review",
            ]
        )
        self.assertEqual(args.command, "compile")
        self.assertEqual(args.compile_command, "reject")
        self.assertEqual(args.decision_key, "route.fix_ci")
        self.assertEqual(args.reason, "manual_review")

    def test_parse_args_rules_promote(self) -> None:
        args = parse_args(
            [
                "rules",
                "promote",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "4",
                "--min-confidence",
                "0.8",
                "--min-accuracy",
                "0.9",
            ]
        )
        self.assertEqual(args.command, "rules")
        self.assertEqual(args.rules_command, "promote")
        self.assertEqual(args.decision_key, "route.fix_ci")
        self.assertEqual(args.min_history, 4)
        self.assertEqual(args.min_confidence, 0.8)
        self.assertEqual(args.min_accuracy, 0.9)

    def test_parse_args_release_checklist(self) -> None:
        args = parse_args(["release", "checklist", "--strict", "--json"])
        self.assertEqual(args.command, "release")
        self.assertEqual(args.release_command, "checklist")
        self.assertTrue(args.strict)
        self.assertTrue(args.json)

    def test_load_json_payload_validation(self) -> None:
        payload = _load_json_payload('{"a":1}')
        self.assertEqual(payload["a"], 1)

        with self.assertRaises(SystemExit):
            _load_json_payload("[]")
        with self.assertRaises(SystemExit):
            _load_json_payload("not-json")

    def test_resolve_run_id_prefers_argument_then_env(self) -> None:
        os.environ["AGENTOS_RUN_ID"] = "run_env"
        self.assertEqual(_resolve_run_id("run_arg"), "run_arg")
        self.assertEqual(_resolve_run_id(None), "run_env")
        os.environ.pop("AGENTOS_RUN_ID", None)
        with self.assertRaises(SystemExit):
            _resolve_run_id(None)

    def test_wrap_and_runs_commands(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.wrap", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run = json.loads(out.strip().splitlines()[-1])
        run_id = run["run_id"]

        code, out, _ = self._run_cli(["runs", "list", "--limit", "5"])
        self.assertEqual(code, 0)
        self.assertIn(run_id, out)

        code, out, _ = self._run_cli(["runs", "show", run_id])
        self.assertEqual(code, 0)
        self.assertIn('"intent": "demo.wrap"', out)

        code, out, _ = self._run_cli(["runs", "trace", run_id])
        self.assertEqual(code, 0)
        self.assertIn('"type": "run_started"', out)
        self.assertIn('"type": "run_finished"', out)

    def test_decision_and_outcome_commands(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.decide", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        code, out, _ = self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "route.fix_ci",
                "--candidate",
                "true",
                "--data-json",
                '{"chosen":"retry"}',
            ]
        )
        self.assertEqual(code, 0)
        decision_id = json.loads(out)["decision_id"]

        code, out, _ = self._run_cli(["decision", "list", "--limit", "10"])
        self.assertEqual(code, 0)
        self.assertIn('"decision_key": "route.fix_ci"', out)

        code, out, _ = self._run_cli(["decision", "show", str(decision_id)])
        self.assertEqual(code, 0)
        self.assertIn('"run_id":', out)

        code, out, _ = self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn('"status": "success"', out)

        code, out, _ = self._run_cli(["runs", "trace", run_id])
        self.assertEqual(code, 0)
        self.assertIn('"type": "decision_recorded"', out)
        self.assertIn('"type": "outcome_recorded"', out)

    def test_missing_entities_return_error_code(self) -> None:
        code, _, err = self._run_cli(["runs", "show", "run_missing"])
        self.assertEqual(code, 1)
        self.assertIn("run not found", err)

        code, _, err = self._run_cli(["runs", "trace", "run_missing"])
        self.assertEqual(code, 1)
        self.assertIn("trace not found", err)

        code, _, err = self._run_cli(["decision", "show", "999999"])
        self.assertEqual(code, 1)
        self.assertIn("decision not found", err)

    def test_patterns_list_outputs_confidence_and_promote_ready(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.patterns", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "route.fix_ci",
                "--candidate",
                "true",
                "--data-json",
                '{"chosen":"retry"}',
            ]
        )
        self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "route.fix_ci",
                "--candidate",
                "true",
                "--data-json",
                '{"chosen":"retry"}',
            ]
        )
        self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "route.fix_ci",
                "--candidate",
                "true",
                "--data-json",
                '{"chosen":"escalate"}',
            ]
        )
        self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "route.docs",
                "--candidate",
                "true",
                "--data-json",
                '{"chosen":"delegate"}',
            ]
        )
        self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "route.docs",
                "--candidate",
                "true",
                "--data-json",
                '{"chosen":"delegate"}',
            ]
        )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )

        code, out, _ = self._run_cli(["patterns", "list", "--min-support", "2", "--limit", "5"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertEqual(len(rows), 2)
        by_key = {row["decision_key"]: row for row in rows}
        self.assertAlmostEqual(by_key["route.fix_ci"]["confidence"], 2 / 3, places=6)
        self.assertAlmostEqual(by_key["route.fix_ci"]["abstain_rate"], 1 / 3, places=6)
        self.assertFalse(by_key["route.fix_ci"]["promote_ready"])
        self.assertEqual(by_key["route.docs"]["confidence"], 1.0)
        self.assertEqual(by_key["route.docs"]["abstain_rate"], 0.0)
        self.assertTrue(by_key["route.docs"]["promote_ready"])

    def test_decision_record_accepts_features_json(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.features", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        code, out, _ = self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "teams.classify_thread",
                "--step",
                "teams.classify_thread",
                "--type",
                "llm",
                "--input-fingerprint",
                "abc123",
                "--output-json",
                '{"chosen":"feedback","confidence":1.0}',
                "--evidence-json",
                "[]",
                "--candidate",
                "true",
                "--features-json",
                '{"is_root": true, "has_mention": true, "channel": "devops"}',
            ]
        )
        self.assertEqual(code, 0)
        decision_id = json.loads(out)["decision_id"]
        self.assertEqual(json.loads(out)["decision_validity"], "valid")

        code, show_out, _ = self._run_cli(["decision", "show", str(decision_id)])
        self.assertEqual(code, 0)
        decision_payload = json.loads(show_out)
        # The features dict round-trips inside payload_json.
        self.assertEqual(
            decision_payload["payload_json"]["features"],
            {"is_root": True, "has_mention": True, "channel": "devops"},
        )

    def test_decision_record_rejects_invalid_features_value_type(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.invalid_features", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        # Nested dict in features value — must fail validation.
        code, out, _ = self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "k",
                "--step",
                "k",
                "--type",
                "llm",
                "--input-fingerprint",
                "fp",
                "--output-json",
                '{"chosen":"x"}',
                "--evidence-json",
                "[]",
                "--candidate",
                "true",
                "--features-json",
                '{"nested": {"oops": 1}}',
            ]
        )
        self.assertEqual(code, 0)  # Stored but marked invalid by default
        validity = json.loads(out)["decision_validity"]
        self.assertEqual(validity, "invalid_schema")

    def test_patterns_list_by_features_groups_by_feature_subspace(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.by_features", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        # Two distinct feature buckets, each unanimous on its choice.
        for _ in range(3):
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "teams.classify_thread",
                    "--step",
                    "teams.classify_thread",
                    "--type",
                    "llm",
                    "--input-fingerprint",
                    "fp1",
                    "--output-json",
                    '{"chosen":"feedback"}',
                    "--evidence-json",
                    "[]",
                    "--candidate",
                    "true",
                    "--features-json",
                    '{"is_root": true, "has_mention": true}',
                ]
            )
        for _ in range(2):
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "teams.classify_thread",
                    "--step",
                    "teams.classify_thread",
                    "--type",
                    "llm",
                    "--input-fingerprint",
                    "fp2",
                    "--output-json",
                    '{"chosen":"skip"}',
                    "--evidence-json",
                    "[]",
                    "--candidate",
                    "true",
                    "--features-json",
                    '{"is_root": false, "has_mention": false}',
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )

        code, out, _ = self._run_cli(["patterns", "list", "--by-features", "--min-support", "2"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertEqual(len(rows), 2)
        by_choice = {r["dominant_choice"]: r for r in rows}
        self.assertEqual(by_choice["feedback"]["support"], 3)
        self.assertEqual(by_choice["feedback"]["confidence"], 1.0)
        self.assertTrue(by_choice["feedback"]["promote_ready"])
        self.assertEqual(by_choice["feedback"]["features"], {"is_root": True, "has_mention": True})
        self.assertEqual(by_choice["skip"]["support"], 2)

    def test_backtest_run_outputs_walk_forward_metrics(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.backtest", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        for chosen in ["retry", "retry", "retry", "escalate", "retry", "retry"]:
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "route.fix_ci",
                    "--candidate",
                    "true",
                    "--data-json",
                    json.dumps({"chosen": chosen}),
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )

        code, out, _ = self._run_cli(
            [
                "backtest",
                "run",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "3",
                "--min-confidence",
                "0.6",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["decision_key"], "route.fix_ci")
        self.assertEqual(payload["candidate_choice"], "retry")
        self.assertEqual(payload["total_observations"], 6)
        self.assertEqual(payload["predictions"], 3)
        self.assertEqual(payload["abstentions"], 3)
        self.assertEqual(payload["correct_predictions"], 2)
        self.assertAlmostEqual(payload["accuracy"], 2 / 3, places=6)
        self.assertAlmostEqual(payload["abstain_rate"], 0.5, places=6)
        self.assertAlmostEqual(payload["coverage_rate"], 0.5, places=6)
        self.assertFalse(payload["promote_ready"])

    def test_backtest_run_handles_not_enough_data(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.backtest.small", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]
        self._run_cli(
            [
                "decision",
                "record",
                "--run-id",
                run_id,
                "--key",
                "route.docs",
                "--candidate",
                "true",
                "--data-json",
                '{"chosen":"delegate"}',
            ]
        )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )
        code, out, _ = self._run_cli(["backtest", "run", "--decision-key", "route.docs"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["error"], "not_enough_data")
        self.assertEqual(payload["total_observations"], 1)

    def test_rules_promote_and_list(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.promote", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        for chosen in ["retry", "retry", "retry", "retry", "retry"]:
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "route.fix_ci",
                    "--candidate",
                    "true",
                    "--data-json",
                    json.dumps({"chosen": chosen}),
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "accepted",
                "--data-json",
                '{"result":"human_accepted"}',
            ]
        )

        code, out, _ = self._run_cli(
            [
                "rules",
                "promote",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "3",
                "--min-confidence",
                "0.8",
                "--min-accuracy",
                "1.0",
                "--rule-id",
                "rule_test_fixed",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["promoted"])
        self.assertEqual(payload["status"], "promoted")
        self.assertEqual(payload["rule_id"], "rule_test_fixed")
        self.assertTrue(payload["fallback_enabled"])

        code, out, _ = self._run_cli(["rules", "list", "--limit", "10"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rule_id"], "rule_test_fixed")
        self.assertEqual(rows[0]["decision_key"], "route.fix_ci")
        self.assertEqual(rows[0]["status"], "promoted")
        self.assertTrue(rows[0]["fallback_enabled"])

    def test_rules_promote_abstains_when_metrics_are_insufficient(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.promote.abstain", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]
        for chosen in ["retry", "retry", "escalate", "retry"]:
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "route.fix_ci",
                    "--candidate",
                    "true",
                    "--data-json",
                    json.dumps({"chosen": chosen}),
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )

        code, out, _ = self._run_cli(
            [
                "rules",
                "promote",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "2",
                "--min-confidence",
                "0.6",
                "--min-accuracy",
                "1.0",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["promoted"])
        self.assertEqual(payload["status"], "abstain")
        self.assertTrue(payload["fallback_enabled"])

    def test_compile_aliases_execute_candidates_backtest_and_promote(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.compile.aliases", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        for chosen in ["retry", "retry", "retry", "retry", "retry"]:
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "route.fix_ci",
                    "--candidate",
                    "true",
                    "--data-json",
                    json.dumps({"chosen": chosen}),
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )

        code, out, _ = self._run_cli(["compile", "candidates", "--min-support", "2", "--limit", "5"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertEqual(rows[0]["decision_key"], "route.fix_ci")
        self.assertEqual(rows[0]["confidence"], 1.0)

        code, out, _ = self._run_cli(
            [
                "compile",
                "backtest",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "3",
                "--min-confidence",
                "0.8",
            ]
        )
        self.assertEqual(code, 0)
        backtest_payload = json.loads(out)
        self.assertEqual(backtest_payload["decision_key"], "route.fix_ci")
        self.assertEqual(backtest_payload["accuracy"], 1.0)

        code, out, _ = self._run_cli(
            [
                "compile",
                "promote",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "3",
                "--min-confidence",
                "0.8",
                "--min-accuracy",
                "1.0",
            ]
        )
        self.assertEqual(code, 0)
        promote_payload = json.loads(out)
        self.assertTrue(promote_payload["promoted"])
        self.assertEqual(promote_payload["status"], "promoted")

    def test_compile_reject_records_rejected_rule(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.compile.reject", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]
        for chosen in ["retry", "retry", "escalate"]:
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "route.fix_ci",
                    "--candidate",
                    "true",
                    "--data-json",
                    json.dumps({"chosen": chosen}),
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "accepted",
                "--data-json",
                '{"result":"human_accepted"}',
            ]
        )

        code, out, _ = self._run_cli(
            [
                "compile",
                "reject",
                "--decision-key",
                "route.fix_ci",
                "--reason",
                "manual_review",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["rejected"])
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["reason"], "manual_review")

        code, out, _ = self._run_cli(["rules", "list", "--limit", "5"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertEqual(rows[0]["status"], "rejected")

    def test_wrap_uses_agentos_yaml_defaults(self) -> None:
        config_path = Path(self.temp_dir.name) / "agentos.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "wrap:",
                    "  intent: demo.config.intent",
                    "  source: config-source",
                    "  capture_stdout: true",
                ]
            ),
            encoding="utf-8",
        )
        cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        try:
            code, out, _ = self._run_cli(["wrap", "--", "python", "-c", "print('ok')"])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]
        code, out, _ = self._run_cli(["runs", "show", run_id])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["intent"], "demo.config.intent")
        self.assertEqual(payload["source"], "config-source")

        code, out, _ = self._run_cli(["runs", "trace", run_id])
        self.assertEqual(code, 0)
        self.assertIn('"type": "stdout"', out)

    def test_wrap_rule_first_can_skip_fallback_when_promoted_rule_matches(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.rule.first", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]
        for _ in range(5):
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "route.fix_ci",
                    "--candidate",
                    "true",
                    "--data-json",
                    '{"chosen":"retry"}',
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )
        self._run_cli(
            [
                "rules",
                "promote",
                "--decision-key",
                "route.fix_ci",
                "--min-history",
                "3",
                "--min-confidence",
                "0.8",
                "--min-accuracy",
                "1.0",
                "--rule-id",
                "rule_skip_fallback",
            ]
        )

        code, out, _ = self._run_cli(
            [
                "wrap",
                "--intent",
                "demo.rule.first.skip",
                "--rule-first",
                "--decision-key",
                "route.fix_ci",
                "--on-rule-match",
                "skip-fallback",
                "--",
                "python",
                "-c",
                "import sys; sys.exit(33)",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["fallback_skipped"])
        self.assertEqual(payload["rule_id"], "rule_skip_fallback")


    def test_release_vertical_slice_end_to_end_with_safe_default_fallback(self) -> None:
        code, out, _ = self._run_cli(
            ["wrap", "--intent", "demo.release.vertical", "--", "python", "-c", "print('ok')"]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        for _ in range(5):
            self._run_cli(
                [
                    "decision",
                    "record",
                    "--run-id",
                    run_id,
                    "--key",
                    "route.release",
                    "--candidate",
                    "true",
                    "--data-json",
                    '{"chosen":"retry"}',
                ]
            )
        self._run_cli(
            [
                "outcome",
                "record",
                "--run-id",
                run_id,
                "--status",
                "success",
                "--data-json",
                '{"result":"green"}',
            ]
        )

        code, out, _ = self._run_cli(["compile", "candidates", "--min-support", "2", "--limit", "10"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        by_key = {row["decision_key"]: row for row in rows}
        self.assertIn("route.release", by_key)
        self.assertEqual(by_key["route.release"]["confidence"], 1.0)

        code, out, _ = self._run_cli(
            [
                "compile",
                "backtest",
                "--decision-key",
                "route.release",
                "--min-history",
                "3",
                "--min-confidence",
                "0.8",
            ]
        )
        self.assertEqual(code, 0)
        backtest_payload = json.loads(out)
        self.assertTrue(backtest_payload["promote_ready"])

        code, out, _ = self._run_cli(
            [
                "compile",
                "promote",
                "--decision-key",
                "route.release",
                "--min-history",
                "3",
                "--min-confidence",
                "0.8",
                "--min-accuracy",
                "1.0",
                "--rule-id",
                "rule_release_vertical",
            ]
        )
        self.assertEqual(code, 0)
        promote_payload = json.loads(out)
        self.assertTrue(promote_payload["promoted"])
        self.assertTrue(promote_payload["fallback_enabled"])

        code, out, _ = self._run_cli(
            [
                "wrap",
                "--intent",
                "demo.release.vertical.observe",
                "--rule-first",
                "--decision-key",
                "route.release",
                "--",
                "python",
                "-c",
                "import sys; sys.exit(0)",
            ]
        )
        self.assertEqual(code, 0)
        observe_payload = json.loads(out)
        self.assertEqual(observe_payload["exit_code"], 0)
        self.assertNotIn("fallback_skipped", observe_payload)

        code, out, _ = self._run_cli(["runs", "trace", observe_payload["run_id"]])
        self.assertEqual(code, 0)
        self.assertIn('"type": "rule_match_checked"', out)
        self.assertIn('"matched": true', out)

    def test_wrap_ingests_decision_file_and_outcome(self) -> None:
        artifact_dir = Path(self.temp_dir.name) / "agentos-artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        decision_file = artifact_dir / "decisions.json"
        decision_file.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "step_id": "classify_failure",
                            "decision_type": "llm",
                            "input_refs": ["job-log.txt"],
                            "output": {"failure_type": "eslint_unused_variable", "confidence": 0.94},
                            "evidence": ["CI log contains no-unused-vars"],
                            "compilation_candidate": True,
                        }
                    ],
                    "outcome": {"status": "success", "tests_passed": True},
                }
            ),
            encoding="utf-8",
        )
        code, out, _ = self._run_cli(
            [
                "wrap",
                "--intent",
                "demo.decision.file",
                "--decision-file",
                str(decision_file),
                "--",
                "python",
                "-c",
                "print('ok')",
            ]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        code, out, _ = self._run_cli(["decision", "list", "--limit", "5"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertEqual(rows[0]["run_id"], run_id)
        self.assertEqual(rows[0]["decision_source"], "decision_file")
        self.assertEqual(rows[0]["decision_validity"], "valid")
        self.assertTrue(rows[0]["compilation_candidate"])

    def test_wrap_strict_decisions_fails_on_invalid_decision_file(self) -> None:
        artifact_dir = Path(self.temp_dir.name) / "agentos-artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        decision_file = artifact_dir / "decisions.json"
        decision_file.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "step_id": "classify_failure",
                            "decision_type": "llm",
                            "output": {"failure_type": "eslint_unused_variable", "confidence": 0.94},
                            "evidence": ["CI log contains no-unused-vars"],
                            "compilation_candidate": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        code, out, _ = self._run_cli(
            [
                "wrap",
                "--intent",
                "demo.decision.strict",
                "--decision-file",
                str(decision_file),
                "--strict-decisions",
                "--",
                "python",
                "-c",
                "print('ok')",
            ]
        )
        self.assertEqual(code, 2)
        payload = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(payload["decision_error"], "invalid_declared_decision")

    def test_wrap_ingests_stdout_decision_markers(self) -> None:
        code, out, _ = self._run_cli(
            [
                "wrap",
                "--intent",
                "demo.stdout.markers",
                "--parse-decision-markers",
                "--",
                "python",
                "-c",
                (
                    "print(\"===AGENTOS_DECISION_START===\")\n"
                    "print(\"{\\\"step_id\\\":\\\"route.fix_ci\\\",\\\"decision_type\\\":\\\"llm\\\",\\\"input_refs\\\":[\\\"ci_failure.txt\\\"],\\\"output\\\":{\\\"chosen\\\":\\\"retry\\\",\\\"confidence\\\":0.9},\\\"evidence\\\":[\\\"signature:flake\\\"],\\\"compilation_candidate\\\":true}\")\n"
                    "print(\"===AGENTOS_DECISION_END===\")"
                ),
            ]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        code, out, _ = self._run_cli(["decision", "list", "--limit", "5"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertEqual(rows[0]["run_id"], run_id)
        self.assertEqual(rows[0]["decision_source"], "stdout_marker")
        self.assertEqual(rows[0]["decision_validity"], "valid")
        self.assertTrue(rows[0]["compilation_candidate"])

    def test_wrap_parse_decision_markers_ignores_plain_logs_without_markers(self) -> None:
        code, out, _ = self._run_cli(
            [
                "wrap",
                "--intent",
                "demo.stdout.no.markers",
                "--parse-decision-markers",
                "--strict-decisions",
                "--",
                "python",
                "-c",
                'print("I think retry might work")',
            ]
        )
        self.assertEqual(code, 0)
        run_id = json.loads(out.strip().splitlines()[-1])["run_id"]

        code, out, _ = self._run_cli(["decision", "list", "--limit", "20"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertFalse(any(row["run_id"] == run_id for row in rows))

    def test_wrap_strict_decisions_fails_on_invalid_stdout_marker(self) -> None:
        code, out, _ = self._run_cli(
            [
                "wrap",
                "--intent",
                "demo.stdout.markers.strict",
                "--parse-decision-markers",
                "--strict-decisions",
                "--",
                "python",
                "-c",
                (
                    "print(\"===AGENTOS_DECISION_START===\")\n"
                    "print(\"{\\\"step_id\\\":\\\"route.fix_ci\\\",\\\"decision_type\\\":\\\"llm\\\",\\\"output\\\":{\\\"chosen\\\":\\\"retry\\\"},\\\"evidence\\\":[],\\\"compilation_candidate\\\":true}\")\n"
                    "print(\"===AGENTOS_DECISION_END===\")"
                ),
            ]
        )
        self.assertEqual(code, 2)
        payload = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(payload["decision_error"], "invalid_declared_decision")

    def test_release_checklist_reports_gates_and_strict_failure_when_artifacts_missing(self) -> None:
        cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        try:
            code, out, _ = self._run_cli(["release", "checklist", "--json"])
            self.assertEqual(code, 0)
            gates = [json.loads(line) for line in out.splitlines() if line.strip()]
            by_id = {row["gate_id"]: row for row in gates}
            self.assertEqual(by_id["vertical_slice_doc"]["status"], "fail")
            self.assertEqual(by_id["release_checklist_doc"]["status"], "fail")
            self.assertEqual(by_id["mvp_spec_doc"]["status"], "fail")
            self.assertEqual(by_id["roadmap_doc"]["status"], "fail")
            self.assertEqual(by_id["readme_release_references"]["status"], "fail")
            self.assertEqual(by_id["data_model_minimum_records"]["status"], "warn")

            code, out, _ = self._run_cli(["release", "checklist", "--strict", "--json"])
            self.assertEqual(code, 2)
            gates = [json.loads(line) for line in out.splitlines() if line.strip()]
            by_id = {row["gate_id"]: row for row in gates}
            self.assertEqual(by_id["vertical_slice_doc"]["status"], "fail")
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
