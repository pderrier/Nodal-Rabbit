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

from .kernel import compute_backtest_metrics
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
    find_divergent_runs,
    has_outcome_with_marker,
    list_decision_choices,
    list_decision_patterns,
    list_decision_patterns_by_features,
    list_decisions,
    list_promoted_feature_rules,
    list_promoted_rules,
    list_runs,
    record_decision,
    record_event,
    record_outcome,
    record_promoted_feature_rule,
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
    decision_record.add_argument(
        "--prompt-version",
        default=None,
        help="Optional non-empty string (e.g. sha256[:12] hash of prompt source). "
             "Lets rule mining filter to decisions made under the *current* prompt; "
             "decisions from older prompt versions can be quarantined when prompts "
             "are revised to fix bugs.",
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
        choices=("success", "accepted", "failure", "unknown", "rejected"),
        help="Outcome status. 'rejected' means the decision is now considered wrong and "
             "should be excluded from rule mining (mining queries already filter "
             "to status IN (success, accepted)).",
    )
    outcome_record.add_argument(
        "--data-json",
        default="{}",
        help="JSON payload for this outcome (default: {})",
    )

    outcome_auto = outcome_sub.add_parser(
        "auto-correct",
        help="Find runs that produced divergent `chosen` values for the same "
             "input_fingerprint within a time window, and auto-record outcomes "
             "(latest = accepted, earlier divergent = rejected). Idempotent.",
    )
    outcome_auto.add_argument(
        "--decision-key", required=True,
        help="Only auto-correct decisions with this decision_key.",
    )
    outcome_auto.add_argument(
        "--within", default="24h",
        help="Time window to scan for divergence. Suffix h or d (default: 24h).",
    )
    outcome_auto.add_argument(
        "--prompt-version", default=None,
        help="Optional: only consider decisions whose prompt_version matches. "
             "Cross-prompt-version divergences are usually expected and shouldn't "
             "be auto-corrected.",
    )
    outcome_auto.add_argument(
        "--dry-run", action="store_true",
        help="Don't write outcomes; just print what would be done.",
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
    patterns_list.add_argument(
        "--prompt-version",
        default=None,
        help="Optional filter (used with --by-features): only consider decisions "
             "whose prompt_version matches. Lets you mine clean data after a "
             "prompt revision instead of letting old buggy decisions skew results.",
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

    rules_extract = rules_sub.add_parser(
        "extract",
        help="Mine deterministic rules from feature-conditioned decisions (decision-tree extractor). "
             "Output is rule *proposals* — promotion to the rule store stays explicit.",
    )
    rules_extract.add_argument("--decision-key", required=True)
    rules_extract.add_argument(
        "--min-coverage", type=int, default=20,
        help="Minimum samples a leaf must cover to qualify as a rule (default: 20)",
    )
    rules_extract.add_argument(
        "--min-precision", type=float, default=0.95,
        help="Minimum class purity at the leaf (1.0 = unanimous; default: 0.95)",
    )
    rules_extract.add_argument(
        "--max-depth", type=int, default=4,
        help="Maximum predicate-conjunction length (default: 4)",
    )
    rules_extract.add_argument(
        "--max-cardinality", type=int, default=10,
        help="Skip features with more distinct values than this (default: 10). "
             "Prevents high-cardinality features like channel_id from dominating the tree.",
    )
    rules_extract.add_argument(
        "--prompt-version",
        default=None,
        help="If set, only mine from decisions whose prompt_version matches. "
             "Use this to quarantine data from older/buggy prompt versions.",
    )

    rules_promote_extracted = rules_sub.add_parser(
        "promote-extracted",
        help="Promote a feature-conditioned rule (proposal from `rules extract`) to the rule store. "
             "Stored alongside key-only promoted rules — distinguished by the predicate_json column.",
    )
    rules_promote_extracted.add_argument("--decision-key", required=True)
    rules_promote_extracted.add_argument(
        "--predicate-json", required=True,
        help='JSON array of {feature, op, value} clauses, e.g. \'[{"feature":"is_root","op":"==","value":true}]\'',
    )
    rules_promote_extracted.add_argument("--chosen", required=True, help="Choice this rule promotes")
    rules_promote_extracted.add_argument(
        "--metrics-json", default='{}',
        help="JSON object of provenance metrics (coverage, precision, support_total, ...)",
    )
    rules_promote_extracted.add_argument(
        "--rule-id",
        help="Optional explicit rule_id (default: auto-generated)",
    )
    rules_promote_extracted.add_argument(
        "--no-fallback", action="store_true",
        help="Disable fallback for this rule (CAUTION: removes safety net)",
    )

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
    if "prompt_version" in payload:
        prompt_version = payload.get("prompt_version")
        # Must be a non-empty string when present. Convention: callers pass a
        # short content hash (e.g. sha256[:12] of the prompt source) so rule
        # mining can filter to decisions made under the *current* prompt.
        if not isinstance(prompt_version, str) or not prompt_version.strip():
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
    if not any([args.step_id, args.decision_type, args.input_refs, args.output_json, args.output_file, args.evidence_json, args.features_json, args.prompt_version, args.candidate]):
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
    if args.prompt_version:
        if not isinstance(args.prompt_version, str) or not args.prompt_version.strip():
            raise SystemExit("--prompt-version must be a non-empty string")
        payload["prompt_version"] = args.prompt_version
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


def _parse_within(spec: str) -> int:
    """Parse a duration spec like '24h' / '7d' / '3600s' to seconds."""
    spec = (spec or "").strip().lower()
    if not spec:
        raise SystemExit("--within must not be empty")
    unit = spec[-1]
    try:
        value = int(spec[:-1]) if unit in ("s", "h", "d") else int(spec)
    except ValueError:
        raise SystemExit(f"--within invalid: {spec!r} (use e.g. 24h, 7d, 3600s)")
    if value <= 0:
        raise SystemExit("--within must be positive")
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    return value  # already seconds, or no unit (treated as seconds)


def cmd_outcome_auto_correct(args: argparse.Namespace) -> int:
    """Find divergent decisions and record latest-wins outcomes idempotently."""
    home = resolve_home()
    conn = ensure_schema(home)
    within_seconds = _parse_within(args.within)

    groups = find_divergent_runs(
        conn,
        decision_key=args.decision_key,
        within_seconds=within_seconds,
        prompt_version=args.prompt_version,
    )

    corrections: list[dict[str, object]] = []
    for group in groups:
        decisions = group["decisions"]
        latest = decisions[-1]  # ts ASC → last is most recent
        latest_chosen = latest["chosen"]
        latest_run_id = latest["run_id"]

        for d in decisions[:-1]:
            if d["chosen"] == latest_chosen:
                continue  # consistent with latest, no correction needed
            # Idempotency marker: rejecting THIS run BECAUSE this specific
            # later run produced a different chosen value.
            marker_value = f"rejected_by:{latest_run_id}"
            if has_outcome_with_marker(
                conn, d["run_id"], "auto_correct_marker", marker_value
            ):
                continue  # already corrected
            payload = {
                "auto_correct_marker": marker_value,
                "decision_key": args.decision_key,
                "input_fingerprint": group["input_fingerprint"],
                "rejected_chosen": d["chosen"],
                "accepted_chosen": latest_chosen,
                "accepted_run_id": latest_run_id,
                "accepted_decision_id": latest["decision_id"],
                "rejected_decision_id": d["decision_id"],
                "ts_rejected": d["ts"],
                "ts_accepted": latest["ts"],
            }
            corrections.append({
                "rejected_run_id": d["run_id"],
                "rejected_decision_id": d["decision_id"],
                "rejected_chosen": d["chosen"],
                "accepted_run_id": latest_run_id,
                "accepted_chosen": latest_chosen,
                "input_fingerprint": group["input_fingerprint"],
                "applied": not args.dry_run,
            })
            if not args.dry_run:
                record_outcome(conn, d["run_id"], "rejected", payload)
                # Mark the latest run as 'accepted' too — once per group is
                # enough; idempotency guard prevents duplicates.
                accepted_marker = f"accepted_for:{group['input_fingerprint']}"
                if not has_outcome_with_marker(
                    conn, latest_run_id, "auto_correct_marker", accepted_marker
                ):
                    record_outcome(conn, latest_run_id, "accepted", {
                        "auto_correct_marker": accepted_marker,
                        "decision_key": args.decision_key,
                        "input_fingerprint": group["input_fingerprint"],
                        "ts_accepted": latest["ts"],
                    })

    summary = {
        "decision_key": args.decision_key,
        "within_seconds": within_seconds,
        "prompt_version": args.prompt_version,
        "divergent_groups": len(groups),
        "corrections": corrections,
        "applied_count": sum(1 for c in corrections if c["applied"]),
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_patterns_list(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    by_features = getattr(args, "by_features", False)
    if by_features:
        rows = list_decision_patterns_by_features(
            conn,
            decision_key=getattr(args, "decision_key", None),
            prompt_version=getattr(args, "prompt_version", None),
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


def cmd_backtest_run(args: argparse.Namespace) -> int:
    home = resolve_home()
    conn = ensure_schema(home)
    choices = list_decision_choices(conn, decision_key=args.decision_key)
    metrics = compute_backtest_metrics(
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
    metrics = compute_backtest_metrics(
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
    metrics = compute_backtest_metrics(
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


def cmd_rules_promote_extracted(args: argparse.Namespace) -> int:
    """Promote a feature-conditioned rule produced by ``rules extract``."""
    home = resolve_home()
    conn = ensure_schema(home)

    try:
        predicate = json.loads(args.predicate_json)
    except json.JSONDecodeError as exc:
        print(f"--predicate-json: invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(predicate, list):
        print("--predicate-json must be a JSON array", file=sys.stderr)
        return 1
    try:
        metrics = json.loads(args.metrics_json)
    except json.JSONDecodeError as exc:
        print(f"--metrics-json: invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(metrics, dict):
        print("--metrics-json must be a JSON object", file=sys.stderr)
        return 1

    rule_id = args.rule_id or create_rule_id()
    record_promoted_feature_rule(
        conn,
        rule_id=rule_id,
        decision_key=args.decision_key,
        predicate=predicate,
        chosen=args.chosen,
        metrics=metrics,
        fallback_enabled=not args.no_fallback,
    )
    print(json.dumps({
        "rule_id": rule_id,
        "decision_key": args.decision_key,
        "chosen": args.chosen,
        "predicate": predicate,
        "fallback_enabled": not args.no_fallback,
        "status": "promoted",
    }, ensure_ascii=False))
    return 0


def cmd_rules_extract(args: argparse.Namespace) -> int:
    """Mine rule proposals from feature-conditioned decisions.

    Prints one JSON line per qualifying rule. Rules are *proposals* —
    promotion to the rule store stays an explicit human-reviewed step.
    """
    from agentos.extractor import extract_rules_from_db

    home = resolve_home()
    conn = ensure_schema(home)
    rules = extract_rules_from_db(
        conn,
        decision_key=args.decision_key,
        prompt_version=getattr(args, "prompt_version", None),
        min_coverage=args.min_coverage,
        min_precision=args.min_precision,
        max_depth=args.max_depth,
        max_cardinality=args.max_cardinality,
    )
    for rule in rules:
        print(json.dumps(rule.to_dict(), ensure_ascii=False))
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
        if args.outcome_command == "auto-correct":
            return cmd_outcome_auto_correct(args)
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
        if args.rules_command == "extract":
            return cmd_rules_extract(args)
        if args.rules_command == "promote-extracted":
            return cmd_rules_promote_extracted(args)
    if args.command == "release":
        if args.release_command == "checklist":
            return cmd_release_checklist(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
