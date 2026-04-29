from __future__ import annotations

import argparse
import json
import os
import re
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
    get_latest_promoted_rule,
    get_decision,
    get_run,
    list_decision_choices,
    list_decision_patterns,
    list_decision_patterns_by_features,
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
DECISION_SOURCES = ("decision_file", "stdout_marker", "cli_record", "sdk_record", "passive_trace")
DECISION_TYPES = ("rule", "llm", "human", "script", "verifier")
VALID_DECISION_SOURCES = {"decision_file", "stdout_marker", "cli_record", "sdk_record"}
DECISION_MARKER_RE = re.compile(
    r"===AGENTOS_DECISION_START===\s*(\{.*?\})\s*===AGENTOS_DECISION_END===",
    re.DOTALL,
)

DEFAULT_CONFIG_PATH = "agentos.yaml"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agentos")
    sub = parser.add_subparsers(dest="command", required=True)

    wrap = sub.add_parser("wrap", help="Wrap an existing command and capture a minimal run trace")
    wrap.add_argument("--intent")
    wrap.add_argument("--source", default="local-cli")
    wrap.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    wrap.add_argument("--rule-first", action="store_true", default=False)
    wrap.add_argument("--decision-key", help="Decision key used to match promoted rules in rule-first mode")
    wrap.add_argument(
        "--on-rule-match",
        choices=("observe", "skip-fallback"),
        default="observe",
        help="When a promoted rule matches: observe (default) or skip process fallback",
    )
    wrap.add_argument("--run-id")
    wrap.add_argument("--decision-file")
    wrap.add_argument("--parse-decision-markers", action="store_true", default=False)
    wrap.add_argument("--strict-decisions", action="store_true", default=False)
    wrap.add_argument("--allow-invalid-decisions", action="store_true", default=True)
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
    decision_record.add_argument("--step", dest="step_id")
    decision_record.add_argument("--type", dest="decision_type", choices=DECISION_TYPES)
    decision_record.add_argument("--source", dest="decision_source", choices=DECISION_SOURCES, default="cli_record")
    decision_record.add_argument("--input-file", dest="input_refs", action="append", default=[])
    decision_record.add_argument("--input-fingerprint")
    decision_record.add_argument("--output-json", default=None)
    decision_record.add_argument("--output-file", default=None)
    decision_record.add_argument("--evidence-json", default=None)
    decision_record.add_argument(
        "--features-json",
        default=None,
        help="JSON object of structured features (str/bool/int/float values) for rule mining",
    )
    decision_record.add_argument("--candidate", choices=("true", "false"), default=None)
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
        choices=("success", "accepted", "failure", "unknown"),
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
    patterns_list.add_argument(
        "--by-features",
        action="store_true",
        help="Group decisions by (decision_key, features) — surfaces feature-conditioned patterns "
             "for rule extraction. Decisions without a `features` field are skipped.",
    )
    patterns_list.add_argument(
        "--decision-key",
        default=None,
        help="Optional filter: only mine patterns for this decision_key (used with --by-features)",
    )

    compile_cmd = sub.add_parser(
        "compile",
        help="Compilation workflow aliases (candidates/backtest/promote) aligned with MVP spec",
    )
    compile_sub = compile_cmd.add_subparsers(dest="compile_command", required=True)

    compile_candidates = compile_sub.add_parser("candidates", help="Alias for patterns list")
    compile_candidates.add_argument("--min-support", type=int, default=2)
    compile_candidates.add_argument("--limit", type=int, default=20)

    compile_backtest = compile_sub.add_parser("backtest", help="Alias for backtest run")
    compile_backtest.add_argument("--decision-key", required=True)
    compile_backtest.add_argument("--min-history", type=int, default=3)
    compile_backtest.add_argument("--min-confidence", type=float, default=1.0)

    compile_promote = compile_sub.add_parser("promote", help="Alias for rules promote")
    compile_promote.add_argument("--decision-key", required=True)
    compile_promote.add_argument("--min-history", type=int, default=3)
    compile_promote.add_argument("--min-confidence", type=float, default=1.0)
    compile_promote.add_argument("--min-accuracy", type=float, default=1.0)
    compile_promote.add_argument("--rule-id")

    compile_reject = compile_sub.add_parser("reject", help="Explicitly reject one deterministic candidate")
    compile_reject.add_argument("--decision-key", required=True)
    compile_reject.add_argument("--min-history", type=int, default=3)
    compile_reject.add_argument("--min-confidence", type=float, default=1.0)
    compile_reject.add_argument("--reason", default="manual_reject")
    compile_reject.add_argument("--rule-id")

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

    rules_reject = rules_sub.add_parser("reject", help="Record an explicit rejection for one deterministic candidate")
    rules_reject.add_argument("--decision-key", required=True)
    rules_reject.add_argument("--min-history", type=int, default=3)
    rules_reject.add_argument("--min-confidence", type=float, default=1.0)
    rules_reject.add_argument("--reason", default="manual_reject")
    rules_reject.add_argument("--rule-id")

    rules_list = rules_sub.add_parser("list", help="List promoted rules")
    rules_list.add_argument("--limit", type=int, default=20)

    release = sub.add_parser("release", help="Release readiness utilities")
    release_sub = release.add_subparsers(dest="release_command", required=True)

    release_checklist = release_sub.add_parser("checklist", help="Evaluate MVP release checklist gates")
    release_checklist.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Return non-zero if any automatic gate fails",
    )
    release_checklist.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit one JSON object per checklist gate",
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


def _parse_simple_yaml(raw: str) -> dict[str, object]:
    parsed: dict[str, object] = {}
    section: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  ") and section:
            if ":" not in stripped:
                continue
            key, value = [part.strip() for part in stripped.split(":", 1)]
            parsed_section = parsed.get(section)
            if not isinstance(parsed_section, dict):
                parsed_section = {}
                parsed[section] = parsed_section
            parsed_section[key] = _coerce_scalar(value)
            continue
        if ":" not in stripped:
            continue
        key, value = [part.strip() for part in stripped.split(":", 1)]
        if value == "":
            parsed[key] = {}
            section = key
        else:
            parsed[key] = _coerce_scalar(value)
            section = None
    return parsed


def _coerce_scalar(value: str) -> object:
    normalized = value.strip().strip("'").strip('"')
    lowered = normalized.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered.isdigit():
        return int(lowered)
    return normalized


def _load_config(path: str) -> dict[str, object]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        return {}
    raw = cfg_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    parsed = _parse_simple_yaml(raw)
    return parsed if isinstance(parsed, dict) else {}


def _resolve_wrap_options(args: argparse.Namespace) -> dict[str, object]:
    config = _load_config(args.config)
    wrap_cfg = config.get("wrap", {}) if isinstance(config.get("wrap"), dict) else {}

    intent = args.intent or wrap_cfg.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        raise SystemExit("agentos wrap requires --intent or wrap.intent in agentos.yaml")

    source = args.source
    if source == "local-cli" and isinstance(wrap_cfg.get("source"), str):
        source = str(wrap_cfg["source"])

    capture_stdout = bool(args.capture_stdout or wrap_cfg.get("capture_stdout") is True)
    capture_stderr = bool(args.capture_stderr or wrap_cfg.get("capture_stderr") is True)
    rule_first = bool(args.rule_first or wrap_cfg.get("rule_first") is True)

    return {
        "intent": intent,
        "source": source,
        "capture_stdout": capture_stdout,
        "capture_stderr": capture_stderr,
        "rule_first": rule_first,
    }


def cmd_wrap(args: argparse.Namespace) -> int:
    command = _require_command_tail(args.cmd)
    options = _resolve_wrap_options(args)
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
            "intent": options["intent"],
            "source": options["source"],
            "command": command,
            "capture_stdout": options["capture_stdout"],
            "capture_stderr": options["capture_stderr"],
            "rule_first": options["rule_first"],
            "decision_key": args.decision_key,
            "on_rule_match": args.on_rule_match,
        },
    )

    env_payload = {"env": _redact_env(dict(os.environ))}
    record_event(conn, run_id, "env_snapshot", env_payload)

    matched_rule = None
    if options["rule_first"] and args.decision_key:
        matched_rule = get_latest_promoted_rule(conn, decision_key=args.decision_key)
        append_trace(
            home,
            run_id,
            "rule_match_checked",
            {"decision_key": args.decision_key, "matched": bool(matched_rule)},
        )

    if matched_rule is not None and args.on_rule_match == "skip-fallback":
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        finished_at = utc_now_iso()
        append_trace(
            home,
            run_id,
            "rule_applied",
            {
                "rule_id": matched_rule["rule_id"],
                "decision_key": matched_rule["decision_key"],
                "candidate_choice": matched_rule["candidate_choice"],
                "fallback_skipped": True,
            },
        )
        append_trace(
            home,
            run_id,
            "run_finished",
            {"exit_code": 0, "duration_ms": duration_ms, "fallback_skipped": True},
        )
        record_run(
            conn,
            RunRecord(
                run_id=run_id,
                intent=str(options["intent"]),
                source=str(options["source"]),
                command=shlex.join(command),
                started_at=started_at,
                finished_at=finished_at,
                exit_code=0,
                duration_ms=duration_ms,
                trace_path=str((home / "runs" / run_id / "trace.jsonl").as_posix()),
            ),
        )
        print(
            json.dumps(
                {"run_id": run_id, "exit_code": 0, "fallback_skipped": True, "rule_id": matched_rule["rule_id"]},
                ensure_ascii=False,
            )
        )
        return 0

    capture_output = bool(options["capture_stdout"] or options["capture_stderr"] or args.parse_decision_markers)
    proc = subprocess.run(
        command,
        text=True,
        capture_output=capture_output,
        check=False,
    )

    duration_ms = int((time.perf_counter() - started_perf) * 1000)
    finished_at = utc_now_iso()

    if options["capture_stdout"]:
        append_trace(home, run_id, "stdout", {"content": proc.stdout or ""})
    if options["capture_stderr"]:
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
            intent=str(options["intent"]),
            source=str(options["source"]),
            command=shlex.join(command),
            started_at=started_at,
            finished_at=finished_at,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            trace_path=str((home / "runs" / run_id / "trace.jsonl").as_posix()),
        ),
    )

    invalid_declared = False
    if args.decision_file:
        invalid_declared = _ingest_decision_file(home, conn, run_id, args.decision_file, allow_invalid=args.allow_invalid_decisions) or invalid_declared
    if args.parse_decision_markers:
        invalid_declared = _ingest_stdout_markers(
            home=home,
            conn=conn,
            run_id=run_id,
            stdout=proc.stdout or "",
            allow_invalid=args.allow_invalid_decisions,
        ) or invalid_declared

    if args.strict_decisions and invalid_declared:
        print(
            json.dumps(
                {"run_id": run_id, "exit_code": proc.returncode, "decision_error": "invalid_declared_decision"},
                ensure_ascii=False,
            )
        )
        return 2

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


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _validate_declared_decision(payload: dict[str, object]) -> str:
    step_id = payload.get("step_id")
    if not isinstance(step_id, str) or not step_id.strip():
        return "missing_step_id"
    decision_type = payload.get("decision_type")
    if decision_type not in DECISION_TYPES:
        return "invalid_schema"
    output = payload.get("output")
    if not isinstance(output, dict):
        return "missing_output"
    confidence = output.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (float, int)) or confidence < 0 or confidence > 1:
            return "invalid_confidence"
    has_input = isinstance(payload.get("input_refs"), list) and len(payload["input_refs"]) > 0
    has_fingerprint = isinstance(payload.get("input_fingerprint"), str) and bool(payload["input_fingerprint"].strip())
    if not (has_input or has_fingerprint):
        return "missing_input_ref"
    if "evidence" not in payload:
        return "invalid_schema"
    evidence = payload.get("evidence")
    if evidence is not None and not isinstance(evidence, list):
        return "invalid_schema"
    if "features" in payload:
        features = payload.get("features")
        if not isinstance(features, dict):
            return "invalid_schema"
        for k, v in features.items():
            if not isinstance(k, str) or not k:
                return "invalid_schema"
            # Primitive feature values only — keep storage flat and SQL-mineable.
            # Note: bool is a subclass of int in Python, both are accepted.
            if not isinstance(v, (str, bool, int, float)):
                return "invalid_schema"
    candidate = _to_bool(payload.get("compilation_candidate"))
    if candidate is None:
        return "invalid_schema"
    return "valid"


def _record_declared_decision(
    *,
    home: Path,
    conn,
    run_id: str,
    payload: dict[str, object],
    source: str,
    allow_invalid: bool,
) -> bool:
    validity = _validate_declared_decision(payload)
    if validity != "valid" and not allow_invalid:
        return True
    candidate = _to_bool(payload.get("compilation_candidate")) is True
    decision_key = str(payload.get("step_id")) if payload.get("step_id") else None
    decision_id = record_decision(
        conn=conn,
        run_id=run_id,
        decision_key=decision_key,
        payload=payload,
        decision_source=source,
        decision_validity=validity,
        compilation_candidate=candidate,
    )
    append_trace(
        home,
        run_id,
        "decision_recorded",
        {
            "decision_id": decision_id,
            "decision_key": decision_key,
            "decision_source": source,
            "decision_validity": validity,
            "compilation_candidate": candidate,
        },
    )
    return validity != "valid"


def _ingest_decision_file(home: Path, conn, run_id: str, decision_file: str, allow_invalid: bool) -> bool:
    path = Path(decision_file)
    if not path.exists():
        append_trace(home, run_id, "decision_file_missing", {"path": decision_file})
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        append_trace(home, run_id, "decision_file_invalid_json", {"path": decision_file})
        return True
    if not isinstance(payload, dict):
        append_trace(home, run_id, "decision_file_invalid_shape", {"path": decision_file})
        return True

    invalid = False
    decisions = payload.get("decisions", [])
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, dict):
                invalid = _record_declared_decision(
                    home=home,
                    conn=conn,
                    run_id=run_id,
                    payload=decision,
                    source="decision_file",
                    allow_invalid=allow_invalid,
                ) or invalid
            else:
                invalid = True
    else:
        invalid = True

    outcome = payload.get("outcome")
    if isinstance(outcome, dict):
        status = outcome.get("status")
        if status in {"success", "accepted", "failure", "unknown"}:
            record_outcome(conn=conn, run_id=run_id, status=str(status), payload=outcome)
            append_trace(home, run_id, "outcome_recorded", {"status": status, "source": "decision_file"})
        else:
            invalid = True
    return invalid


def _ingest_stdout_markers(*, home: Path, conn, run_id: str, stdout: str, allow_invalid: bool) -> bool:
    invalid = False
    for match in DECISION_MARKER_RE.finditer(stdout):
        block = match.group(1)
        try:
            decision = json.loads(block)
        except json.JSONDecodeError:
            invalid = True
            continue
        if not isinstance(decision, dict):
            invalid = True
            continue
        invalid = _record_declared_decision(
            home=home,
            conn=conn,
            run_id=run_id,
            payload=decision,
            source="stdout_marker",
            allow_invalid=allow_invalid,
        ) or invalid
    return invalid


def _build_declared_decision_payload(args: argparse.Namespace, base_payload: dict[str, object]) -> dict[str, object]:
    if not any([args.step_id, args.decision_type, args.input_refs, args.output_json, args.output_file, args.evidence_json, args.features_json, args.candidate]):
        return base_payload

    payload = dict(base_payload)
    if args.step_id:
        payload["step_id"] = args.step_id
    if args.decision_type:
        payload["decision_type"] = args.decision_type
    if args.input_refs:
        payload["input_refs"] = args.input_refs
    if args.input_fingerprint:
        payload["input_fingerprint"] = args.input_fingerprint
    if args.output_json:
        payload["output"] = _load_json_payload(args.output_json)
    if args.output_file:
        output_payload = json.loads(Path(args.output_file).read_text(encoding="utf-8"))
        if not isinstance(output_payload, dict):
            raise SystemExit("--output-file must contain a JSON object")
        payload["output"] = output_payload
    if args.evidence_json:
        evidence = json.loads(args.evidence_json)
        if not isinstance(evidence, list):
            raise SystemExit("--evidence-json must contain a JSON array")
        payload["evidence"] = evidence
    if args.features_json:
        features = json.loads(args.features_json)
        if not isinstance(features, dict):
            raise SystemExit("--features-json must contain a JSON object")
        payload["features"] = features
    if args.candidate is not None:
        payload["compilation_candidate"] = args.candidate == "true"
    return payload


def cmd_decision_record(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    run_id = _resolve_run_id(args.run_id)
    payload = _build_declared_decision_payload(args, _load_json_payload(args.data_json))
    decision_validity = _validate_declared_decision(payload) if "step_id" in payload else "valid"
    compilation_candidate = _to_bool(payload.get("compilation_candidate")) is True
    decision_key = args.decision_key or (str(payload["step_id"]) if isinstance(payload.get("step_id"), str) else None)
    decision_id = record_decision(
        conn=conn,
        run_id=run_id,
        decision_key=decision_key,
        payload=payload,
        decision_source=args.decision_source,
        decision_validity=decision_validity,
        compilation_candidate=compilation_candidate,
    )
    append_trace(
        home,
        run_id,
        "decision_recorded",
        {
            "decision_id": decision_id,
            "decision_key": decision_key,
            "decision_source": args.decision_source,
            "decision_validity": decision_validity,
            "compilation_candidate": compilation_candidate,
        },
    )
    print(
        json.dumps(
            {
                "decision_id": decision_id,
                "run_id": run_id,
                "decision_key": decision_key,
                "decision_source": args.decision_source,
                "decision_validity": decision_validity,
                "compilation_candidate": compilation_candidate,
            },
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
                    "decision_source": row["decision_source"],
                    "decision_validity": row["decision_validity"],
                    "compilation_candidate": bool(row["compilation_candidate"]),
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
                "decision_source": row["decision_source"],
                "decision_validity": row["decision_validity"],
                "compilation_candidate": bool(row["compilation_candidate"]),
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
    by_features = getattr(args, "by_features", False)
    if by_features:
        rows = list_decision_patterns_by_features(
            conn,
            decision_key=getattr(args, "decision_key", None),
            min_support=args.min_support,
            limit=args.limit,
        )
        for row in rows:
            confidence = float(row["confidence"])
            print(
                json.dumps(
                    {
                        "decision_key": row["decision_key"],
                        "features": row["features"],
                        "dominant_choice": row["dominant_choice"],
                        "support": row["support"],
                        "dominant_count": row["dominant_count"],
                        "confidence": confidence,
                        "abstain_rate": round(max(0.0, 1.0 - confidence), 6),
                        "promote_ready": confidence == 1.0,
                    },
                    ensure_ascii=False,
                )
            )
        return 0
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


def cmd_rules_reject(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    choices = list_decision_choices(conn, decision_key=args.decision_key)
    metrics = _compute_backtest_metrics(
        decision_key=args.decision_key,
        choices=choices,
        min_history=args.min_history,
        min_confidence=args.min_confidence,
    )
    candidate_choice = str(metrics.get("candidate_choice", "__abstain__"))
    rule_id = create_rule_id(args.rule_id)
    record_promoted_rule(
        conn,
        PromotedRuleRecord(
            rule_id=rule_id,
            decision_key=args.decision_key,
            candidate_choice=candidate_choice,
            status="rejected",
            fallback_enabled=True,
            metrics_json=json.dumps(
                {"reason": args.reason, "rejected": True, "metrics": metrics},
                ensure_ascii=False,
            ),
            promoted_at=utc_now_iso(),
        ),
    )
    print(
        json.dumps(
            {
                "rejected": True,
                "status": "rejected",
                "rule_id": rule_id,
                "decision_key": args.decision_key,
                "candidate_choice": candidate_choice,
                "reason": args.reason,
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


def cmd_release_checklist(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    now = utc_now_iso()
    cwd = Path.cwd()

    def _count(query: str, params: tuple[object, ...] = ()) -> int:
        row = conn.execute(query, params).fetchone()
        return int(row[0]) if row else 0

    gates: list[dict[str, object]] = []

    release_artifacts = (
        ("vertical_slice_doc", "VERTICAL_SLICE_MVP_RELEASE.md"),
        ("release_checklist_doc", "RELEASE_MVP_CHECKLIST.md"),
        ("mvp_spec_doc", "agentos_mvp_v0_3.md"),
        ("roadmap_doc", "BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md"),
    )
    for gate_id, filename in release_artifacts:
        exists = (cwd / filename).exists()
        gates.append(
            {
                "gate_id": gate_id,
                "description": f"Required release artifact exists: {filename}",
                "status": "pass" if exists else "fail",
                "checked_at": now,
                "details": {"path": str((cwd / filename).as_posix()), "exists": exists},
            }
        )

    readme_path = cwd / "README.md"
    readme_exists = readme_path.exists()
    readme_raw = readme_path.read_text(encoding="utf-8") if readme_exists else ""
    readme_expectations = {
        "agentos_mvp_v0_3.md": "canonical MVP spec referenced",
        "BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md": "roadmap referenced",
        "VERTICAL_SLICE_MVP_RELEASE.md": "vertical slice referenced",
        "RELEASE_MVP_CHECKLIST.md": "release checklist referenced",
        "python -m agentos release checklist": "release checklist command referenced",
    }
    missing_expectations = [item for item in readme_expectations if item not in readme_raw]
    gates.append(
        {
            "gate_id": "readme_release_references",
            "description": "README references MVP spec, roadmap, release artifacts, and executable release checklist command",
            "status": "pass" if readme_exists and not missing_expectations else "fail",
            "checked_at": now,
            "details": {
                "readme_path": str(readme_path.as_posix()),
                "readme_exists": readme_exists,
                "missing_items": missing_expectations,
            },
        }
    )

    runs_count = _count("SELECT COUNT(*) FROM runs")
    decisions_count = _count("SELECT COUNT(*) FROM decisions")
    outcomes_count = _count("SELECT COUNT(*) FROM outcomes")
    gates.append(
        {
            "gate_id": "data_model_minimum_records",
            "description": "Runs/decisions/outcomes records exist for MVP evidence",
            "status": "pass" if (runs_count > 0 and decisions_count > 0 and outcomes_count > 0) else "warn",
            "checked_at": now,
            "details": {
                "runs": runs_count,
                "decisions": decisions_count,
                "outcomes": outcomes_count,
            },
        }
    )

    trace_missing = _count("SELECT COUNT(*) FROM runs WHERE trace_path IS NULL OR trace_path = ''")
    gates.append(
        {
            "gate_id": "trace_path_persisted",
            "description": "All persisted runs include a trace path",
            "status": "pass" if trace_missing == 0 else "fail",
            "checked_at": now,
            "details": {"runs_missing_trace_path": trace_missing},
        }
    )

    rules_without_fallback = _count("SELECT COUNT(*) FROM promoted_rules WHERE fallback_enabled != 1")
    gates.append(
        {
            "gate_id": "fallback_policy_preserved",
            "description": "All stored promoted/rejected rules keep fallback enabled",
            "status": "pass" if rules_without_fallback == 0 else "fail",
            "checked_at": now,
            "details": {"rules_without_fallback": rules_without_fallback},
        }
    )

    if args.json:
        for gate in gates:
            print(json.dumps(gate, ensure_ascii=False))
    else:
        for gate in gates:
            print(
                f"[{str(gate['status']).upper()}] {gate['gate_id']}: {gate['description']}"
            )
            print(json.dumps(gate["details"], ensure_ascii=False))

    has_failures = any(gate["status"] == "fail" for gate in gates)
    if args.strict and has_failures:
        return 2
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
    if args.command == "compile":
        if args.compile_command == "candidates":
            return cmd_patterns_list(args)
        if args.compile_command == "backtest":
            return cmd_backtest_run(args)
        if args.compile_command == "promote":
            return cmd_rules_promote(args)
        if args.compile_command == "reject":
            return cmd_rules_reject(args)
    if args.command == "backtest":
        if args.backtest_command == "run":
            return cmd_backtest_run(args)
    if args.command == "rules":
        if args.rules_command == "promote":
            return cmd_rules_promote(args)
        if args.rules_command == "reject":
            return cmd_rules_reject(args)
        if args.rules_command == "list":
            return cmd_rules_list(args)
    if args.command == "release":
        if args.release_command == "checklist":
            return cmd_release_checklist(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
