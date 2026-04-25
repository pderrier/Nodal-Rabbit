from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from .storage import (
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
    resolve_home,
    utc_now_iso,
)


REDACT_PATTERNS = ("TOKEN", "SECRET", "PASSWORD", "KEY")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agentos")
    sub = parser.add_subparsers(dest="command", required=True)

    wrap = sub.add_parser("wrap", help="Wrap an existing command and capture a minimal run trace")
    wrap.add_argument("--intent", required=True)
    wrap.add_argument("--source", default="local-cli")
    wrap.add_argument("--run-id")
    wrap.add_argument("--capture-stdout", action="store_true", default=False)
    wrap.add_argument("--capture-stderr", action="store_true", default=False)
    wrap.add_argument("cmd", nargs=argparse.REMAINDER)

    runs = sub.add_parser("runs", help="Inspect recorded runs")
    runs_sub = runs.add_subparsers(dest="runs_command", required=True)

    runs_list = runs_sub.add_parser("list", help="List runs")
    runs_list.add_argument("--limit", type=int, default=20)

    runs_show = runs_sub.add_parser("show", help="Show one run")
    runs_show.add_argument("run_id")

    runs_trace = runs_sub.add_parser("trace", help="Show trace JSONL for one run")
    runs_trace.add_argument("run_id")

    decision = sub.add_parser("decision", help="Record and inspect decisions")
    decision_sub = decision.add_subparsers(dest="decision_command", required=True)

    decision_record = decision_sub.add_parser("record", help="Record one decision event")
    decision_record.add_argument("--run-id", help="Defaults to AGENTOS_RUN_ID if omitted")
    decision_record.add_argument("--key", dest="decision_key", help="Decision key/fingerprint")
    decision_record.add_argument(
        "--data-json",
        default="{}",
        help="JSON payload for this decision (default: {})",
    )

    decision_list = decision_sub.add_parser("list", help="List recent decisions")
    decision_list.add_argument("--limit", type=int, default=20)

    decision_show = decision_sub.add_parser("show", help="Show one decision")
    decision_show.add_argument("decision_id", type=int)

    outcome = sub.add_parser("outcome", help="Record an outcome linked to a run")
    outcome_sub = outcome.add_subparsers(dest="outcome_command", required=True)

    outcome_record = outcome_sub.add_parser("record", help="Record one outcome event")
    outcome_record.add_argument("--run-id", help="Defaults to AGENTOS_RUN_ID if omitted")
    outcome_record.add_argument(
        "--status",
        required=True,
        choices=("success", "failure", "unknown"),
        help="Outcome status",
    )
    outcome_record.add_argument(
        "--data-json",
        default="{}",
        help="JSON payload for this outcome (default: {})",
    )

    return parser.parse_args(argv)


def _redact_env(env: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in env.items():
        if any(pattern in key.upper() for pattern in REDACT_PATTERNS):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


def _require_command_tail(cmd: list[str]) -> list[str]:
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        raise SystemExit("agentos wrap requires a command after '--'")
    return cmd


def cmd_wrap(args: argparse.Namespace) -> int:
    command = _require_command_tail(args.cmd)
    home = resolve_home()
    conn = ensure_schema(home)

    run_id = create_run_id(args.run_id)
    os.environ["AGENTOS_RUN_ID"] = run_id

    started_at = utc_now_iso()
    started_perf = time.perf_counter()

    append_trace(
        home,
        run_id,
        "run_started",
        {
            "intent": args.intent,
            "source": args.source,
            "command": command,
            "capture_stdout": bool(args.capture_stdout),
            "capture_stderr": bool(args.capture_stderr),
        },
    )

    env_payload = {"env": _redact_env(dict(os.environ))}
    record_event(conn, run_id, "env_snapshot", env_payload)

    proc = subprocess.run(
        command,
        text=True,
        capture_output=(args.capture_stdout or args.capture_stderr),
        check=False,
    )

    duration_ms = int((time.perf_counter() - started_perf) * 1000)
    finished_at = utc_now_iso()

    if args.capture_stdout:
        append_trace(home, run_id, "stdout", {"content": proc.stdout or ""})
    if args.capture_stderr:
        append_trace(home, run_id, "stderr", {"content": proc.stderr or ""})

    append_trace(
        home,
        run_id,
        "run_finished",
        {"exit_code": proc.returncode, "duration_ms": duration_ms},
    )

    record_run(
        conn,
        RunRecord(
            run_id=run_id,
            intent=args.intent,
            source=args.source,
            command=shlex.join(command),
            started_at=started_at,
            finished_at=finished_at,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            trace_path=str((home / "runs" / run_id / "trace.jsonl").as_posix()),
        ),
    )

    print(json.dumps({"run_id": run_id, "exit_code": proc.returncode}, ensure_ascii=False))
    return proc.returncode


def cmd_runs_list(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    runs = list_runs(conn, limit=args.limit)
    for row in runs:
        print(
            json.dumps(
                {
                    "run_id": row["run_id"],
                    "intent": row["intent"],
                    "exit_code": row["exit_code"],
                    "started_at": row["started_at"],
                    "duration_ms": row["duration_ms"],
                },
                ensure_ascii=False,
            )
        )
    return 0


def cmd_runs_show(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    row = get_run(conn, args.run_id)
    if not row:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    print(json.dumps(dict(row), ensure_ascii=False, indent=2))
    return 0


def cmd_runs_trace(args: argparse.Namespace) -> int:
    home = resolve_home()
    trace_path = Path(home / "runs" / args.run_id / "trace.jsonl")
    if not trace_path.exists():
        print(f"trace not found: {trace_path}", file=sys.stderr)
        return 1
    print(trace_path.read_text(encoding="utf-8"), end="")
    return 0


def _load_json_payload(raw_payload: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("payload must be a JSON object")
    return payload


def _resolve_run_id(run_id: str | None) -> str:
    resolved = run_id or os.getenv("AGENTOS_RUN_ID")
    if not resolved:
        raise SystemExit("run_id is required (use --run-id or set AGENTOS_RUN_ID)")
    return resolved


def cmd_decision_record(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    run_id = _resolve_run_id(args.run_id)
    payload = _load_json_payload(args.data_json)
    decision_id = record_decision(
        conn=conn,
        run_id=run_id,
        decision_key=args.decision_key,
        payload=payload,
    )
    append_trace(
        home,
        run_id,
        "decision_recorded",
        {"decision_id": decision_id, "decision_key": args.decision_key, "payload": payload},
    )
    print(
        json.dumps(
            {"decision_id": decision_id, "run_id": run_id, "decision_key": args.decision_key},
            ensure_ascii=False,
        )
    )
    return 0


def cmd_decision_list(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    decisions = list_decisions(conn, limit=args.limit)
    for row in decisions:
        print(
            json.dumps(
                {
                    "id": row["id"],
                    "run_id": row["run_id"],
                    "ts": row["ts"],
                    "decision_key": row["decision_key"],
                    "payload_json": json.loads(row["payload_json"]),
                },
                ensure_ascii=False,
            )
        )
    return 0


def cmd_decision_show(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    row = get_decision(conn, args.decision_id)
    if not row:
        print(f"decision not found: {args.decision_id}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "ts": row["ts"],
                "decision_key": row["decision_key"],
                "payload_json": json.loads(row["payload_json"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_outcome_record(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    run_id = _resolve_run_id(args.run_id)
    payload = _load_json_payload(args.data_json)
    outcome_id = record_outcome(
        conn=conn,
        run_id=run_id,
        status=args.status,
        payload=payload,
    )
    append_trace(
        home,
        run_id,
        "outcome_recorded",
        {"outcome_id": outcome_id, "status": args.status, "payload": payload},
    )
    print(
        json.dumps(
            {"outcome_id": outcome_id, "run_id": run_id, "status": args.status},
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "wrap":
        return cmd_wrap(args)
    if args.command == "runs":
        if args.runs_command == "list":
            return cmd_runs_list(args)
        if args.runs_command == "show":
            return cmd_runs_show(args)
        if args.runs_command == "trace":
            return cmd_runs_trace(args)
    if args.command == "decision":
        if args.decision_command == "record":
            return cmd_decision_record(args)
        if args.decision_command == "list":
            return cmd_decision_list(args)
        if args.decision_command == "show":
            return cmd_decision_show(args)
    if args.command == "outcome":
        if args.outcome_command == "record":
            return cmd_outcome_record(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
