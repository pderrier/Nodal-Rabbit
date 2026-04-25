from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from collections import Counter

from .storage import (
    PromotedRuleRecord,
    RunRecord,
    append_trace,
    create_rule_id,
    create_run_id,
    ensure_schema,
    get_decision,
    get_run,
    list_decision_choices,
    list_decision_patterns,
    list_decisions,
    list_promoted_rules,
    list_runs,
    record_decision,
    record_event,
    record_outcome,
    record_promoted_rule,
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

    patterns = sub.add_parser(
        "patterns",
        help="Detect repeated decision patterns for deterministic rule candidates",
    )
    patterns_sub = patterns.add_subparsers(dest="patterns_command", required=True)

    patterns_list = patterns_sub.add_parser("list", help="List repeated decision patterns")
    patterns_list.add_argument("--min-support", type=int, default=2)
    patterns_list.add_argument("--limit", type=int, default=20)

    backtest = sub.add_parser("backtest", help="Backtest deterministic decision rules")
    backtest_sub = backtest.add_subparsers(dest="backtest_command", required=True)

    backtest_run = backtest_sub.add_parser("run", help="Run walk-forward backtest for one decision key")
    backtest_run.add_argument("--decision-key", required=True)
    backtest_run.add_argument("--min-history", type=int, default=3)
    backtest_run.add_argument("--min-confidence", type=float, default=1.0)

    rules = sub.add_parser("rules", help="Promote and inspect deterministic rules with fallback")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)

    rules_promote = rules_sub.add_parser("promote", help="Promote one deterministic candidate with metrics")
    rules_promote.add_argument("--decision-key", required=True)
    rules_promote.add_argument("--min-history", type=int, default=3)
    rules_promote.add_argument("--min-confidence", type=float, default=1.0)
    rules_promote.add_argument("--min-accuracy", type=float, default=1.0)
    rules_promote.add_argument("--rule-id")

    rules_list = rules_sub.add_parser("list", help="List promoted rules")
    rules_list.add_argument("--limit", type=int, default=20)

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


def cmd_patterns_list(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    rows = list_decision_patterns(conn, min_support=args.min_support, limit=args.limit)
    for row in rows:
        confidence = float(row["confidence"])
        abstain_rate = max(0.0, 1.0 - confidence)
        print(
            json.dumps(
                {
                    "decision_key": row["decision_key"],
                    "dominant_choice": row["dominant_choice"],
                    "support": row["support"],
                    "dominant_count": row["dominant_count"],
                    "confidence": confidence,
                    "abstain_rate": round(abstain_rate, 6),
                    "promote_ready": confidence == 1.0,
                },
                ensure_ascii=False,
            )
        )
    return 0


def _dominant_choice(choices: list[str]) -> tuple[str, float]:
    counts = Counter(choices)
    winner, winner_count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return winner, winner_count / len(choices)


def _compute_backtest_metrics(
    decision_key: str,
    choices: list[str],
    min_history: int,
    min_confidence: float,
) -> dict[str, object]:
    total = len(choices)
    if total < 2:
        return {
            "decision_key": decision_key,
            "error": "not_enough_data",
            "total_observations": total,
        }

    correct = 0
    predicted = 0
    abstained = 0

    for idx in range(total):
        if idx < min_history:
            abstained += 1
            continue

        history = choices[:idx]
        dominant, confidence = _dominant_choice(history)
        if confidence < min_confidence:
            abstained += 1
            continue

        predicted += 1
        if choices[idx] == dominant:
            correct += 1

    final_dominant, final_confidence = _dominant_choice(choices)
    accuracy = (correct / predicted) if predicted else 0.0
    abstain_rate = abstained / total
    coverage_rate = predicted / total

    return {
        "decision_key": decision_key,
        "total_observations": total,
        "min_history": min_history,
        "min_confidence": min_confidence,
        "candidate_choice": final_dominant,
        "candidate_confidence": round(final_confidence, 6),
        "predictions": predicted,
        "abstentions": abstained,
        "correct_predictions": correct,
        "accuracy": round(accuracy, 6),
        "abstain_rate": round(abstain_rate, 6),
        "coverage_rate": round(coverage_rate, 6),
        "promote_ready": predicted > 0 and accuracy == 1.0,
    }


def cmd_backtest_run(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    choices = list_decision_choices(conn, decision_key=args.decision_key)
    metrics = _compute_backtest_metrics(
        decision_key=args.decision_key,
        choices=choices,
        min_history=args.min_history,
        min_confidence=args.min_confidence,
    )
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


def cmd_rules_promote(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    choices = list_decision_choices(conn, decision_key=args.decision_key)
    metrics = _compute_backtest_metrics(
        decision_key=args.decision_key,
        choices=choices,
        min_history=args.min_history,
        min_confidence=args.min_confidence,
    )
    if metrics.get("error") == "not_enough_data":
        print(
            json.dumps(
                {
                    "promoted": False,
                    "status": "abstain",
                    "reason": "not_enough_data",
                    "fallback_enabled": True,
                    "metrics": metrics,
                },
                ensure_ascii=False,
            )
        )
        return 0

    accuracy = float(metrics["accuracy"])
    predictions = int(metrics["predictions"])
    candidate_choice = str(metrics["candidate_choice"])
    can_promote = predictions > 0 and accuracy >= args.min_accuracy
    status = "promoted" if can_promote else "abstain"

    rule_id = create_rule_id(args.rule_id) if can_promote else None
    if can_promote and rule_id:
        record_promoted_rule(
            conn,
            PromotedRuleRecord(
                rule_id=rule_id,
                decision_key=args.decision_key,
                candidate_choice=candidate_choice,
                status=status,
                fallback_enabled=True,
                metrics_json=json.dumps(metrics, ensure_ascii=False),
                promoted_at=utc_now_iso(),
            ),
        )

    print(
        json.dumps(
            {
                "promoted": can_promote,
                "status": status,
                "rule_id": rule_id,
                "decision_key": args.decision_key,
                "candidate_choice": candidate_choice,
                "min_accuracy": args.min_accuracy,
                "fallback_enabled": True,
                "metrics": metrics,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_rules_list(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    rows = list_promoted_rules(conn, limit=args.limit)
    for row in rows:
        print(
            json.dumps(
                {
                    "rule_id": row["rule_id"],
                    "decision_key": row["decision_key"],
                    "candidate_choice": row["candidate_choice"],
                    "status": row["status"],
                    "fallback_enabled": bool(row["fallback_enabled"]),
                    "metrics_json": json.loads(row["metrics_json"]),
                    "promoted_at": row["promoted_at"],
                },
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
    if args.command == "patterns":
        if args.patterns_command == "list":
            return cmd_patterns_list(args)
    if args.command == "backtest":
        if args.backtest_command == "run":
            return cmd_backtest_run(args)
    if args.command == "rules":
        if args.rules_command == "promote":
            return cmd_rules_promote(args)
        if args.rules_command == "list":
            return cmd_rules_list(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
