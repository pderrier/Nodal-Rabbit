from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
