# AgentOS (MVP v0)

AgentOS is a **wrapper-first execution and trace layer** for existing automation.

It is designed to help teams progressively move from repeated agentic/manual decisions to deterministic rules, while keeping safe fallback behavior.

## What AgentOS is (MVP)

In MVP, AgentOS focuses on:

- Wrapping existing scripts, CI jobs, and headless agent commands.
- Tracing runs, decisions, and outcomes.
- Detecting repeated patterns.
- Backtesting deterministic rule candidates.
- Promoting conservative rules with metrics.
- Running rule-first with fallback preserved by default.

Core operating rule:

```text
Run capture is automatic.
Decision capture is declarative.
Compilation requires validated decisions and outcomes.
```

Core loop:

```text
wrap existing process
→ trace decisions
→ detect repeated patterns
→ backtest deterministic rules
→ promote rules
→ run rule-first with fallback
```

## What AgentOS is not (MVP)

AgentOS MVP is **not**:

- A coding agent.
- A chatbot.
- A full workflow orchestrator.
- A replacement for your existing scripts, MCP tools, or CI system.

## MVP principles

- **Wrapper-first adoption**: no forced rewrite of existing automation.
- **Fallback by default**: promoted/compiled rules must not remove fallback.
- **Conservative compilation**: rules abstain when uncertain.
- **Transparent evidence**: promotion requires backtest metrics.
- **Simple local primitives**: CLI, SQLite, JSONL, filesystem artifacts.

## High-level architecture

AgentOS sits around existing workers:

- Existing scripts / CI jobs / Codex / Claude / custom tooling perform tasks.
- AgentOS records execution context and decisions.
- AgentOS analyzes repetition and proposes deterministic candidates.
- AgentOS backtests candidates before promotion.
- Runtime can apply rule-first routing, then fallback to original process.

## Decision capture model (MVP)

AgentOS starts by wrapping existing automation:

```bash
agentos wrap --intent gitlab.fix_ci -- ./run-existing-agent.sh
```

This captures the run.

To capture LLM decisions for compilation, the process must declare operational decisions through a decision file, stdout markers, or explicit instrumentation.

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --decision-file agentos-artifacts/decisions.json \
  -- ./run-existing-agent.sh
```

AgentOS does not infer hidden model reasoning.
It compiles only validated declared decisions with outcomes.

## Repository contents

- `agentos_mvp_v0_3.md` — canonical MVP product/technical specification.
- `BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md` — six-week delivery roadmap and prioritized backlog.
- `POSITIONING.md` — positioning document covering prior art, non-goals, and project rationale.

## Getting started

This repository currently documents the MVP direction and delivery plan.

Suggested first steps:

1. Read the canonical spec in `agentos_mvp_v0_3.md`.
2. Review the roadmap in `BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md`.
3. Align implementation work with MVP scope and anti-drift constraints.
4. Read `POSITIONING.md` for positioning details and prior-art boundaries.


## Implementation status (as of 2026-04-25)

A first MVP bootstrap is now available in this repository:

- Python CLI scaffold (`agentos`).
- `agentos wrap --intent ... -- <command>` to execute existing scripts without rewrite.
- Local persistence with SQLite + JSONL traces under `.agentos/`.
- Basic inspection commands: `agentos runs list`, `agentos runs show`, `agentos runs trace`.
- Instrumentation commands: `agentos decision record|list|show` and `agentos outcome record`.
- Pattern detection command: `agentos patterns list` to identify repeated decisions and compute conservative rule metrics.
- Walk-forward backtest command: `agentos backtest run` for deterministic candidates before promotion.
- Rule promotion command: `agentos rules promote` with fallback preserved and evidence persisted locally.
- Rule rejection command: `agentos rules reject` for explicit non-promotion decisions with recorded evidence.
- MVP spec aliases are also available via `agentos compile candidates|backtest|promote|reject`.
- Optional config file support: `agentos.yaml` with `wrap.intent`, `wrap.source`, `wrap.capture_stdout`, `wrap.capture_stderr`, and `wrap.rule_first`.

Quick local run:

```bash
python -m agentos wrap --intent demo.echo -- echo "hello"
python -m agentos decision record --run-id <run_id> --key route.fix_ci --data-json '{"chosen":"retry"}'
python -m agentos outcome record --run-id <run_id> --status success --data-json '{"ci_pipeline":"green"}'
python -m agentos runs list
```

Pattern detection example:

```bash
# record repeated decisions with a "chosen" field
python -m agentos decision record --run-id <run_id> --key route.fix_ci --data-json '{"chosen":"retry"}'
python -m agentos decision record --run-id <run_id> --key route.fix_ci --data-json '{"chosen":"retry"}'
python -m agentos decision record --run-id <run_id> --key route.fix_ci --data-json '{"chosen":"escalate"}'

# detect repeated patterns with support and abstention-aware metrics
python -m agentos patterns list --min-support 2 --limit 20
# equivalent alias aligned with MVP spec wording
python -m agentos compile candidates --min-support 2 --limit 20

# backtest one deterministic candidate with abstention constraints
python -m agentos backtest run --decision-key route.fix_ci --min-history 3 --min-confidence 0.8
# equivalent alias aligned with MVP spec wording
python -m agentos compile backtest --decision-key route.fix_ci --min-history 3 --min-confidence 0.8

# promote only if backtest metrics satisfy your threshold; fallback stays enabled
python -m agentos rules promote --decision-key route.fix_ci --min-history 3 --min-confidence 0.8 --min-accuracy 1.0
# equivalent alias aligned with MVP spec wording
python -m agentos compile promote --decision-key route.fix_ci --min-history 3 --min-confidence 0.8 --min-accuracy 1.0

# explicit rejection (records rationale + metrics snapshot)
python -m agentos rules reject --decision-key route.fix_ci --reason "manual_review_required"
python -m agentos compile reject --decision-key route.fix_ci --reason "manual_review_required"
python -m agentos rules list --limit 20
```

Rule-first runtime (conservative by default):

```bash
# check promoted rule first, but still run fallback process by default ("observe")
python -m agentos wrap --intent demo.rule_first --rule-first --decision-key route.fix_ci -- echo "still runs fallback"

# explicit opt-in to skip fallback if a promoted rule matches
python -m agentos wrap --intent demo.rule_first --rule-first --decision-key route.fix_ci --on-rule-match skip-fallback -- echo "fallback skipped on match"
```

Expected output shape:

```json
{
  "decision_key": "route.fix_ci",
  "dominant_choice": "retry",
  "support": 3,
  "dominant_count": 2,
  "confidence": 0.666667,
  "abstain_rate": 0.333333,
  "promote_ready": false
}
```

Interpretation in MVP:

- `confidence` is empirical dominance of the top deterministic choice in past traces.
- `abstain_rate` (`1 - confidence`) quantifies uncertainty; higher values indicate conservative abstention is required.
- `promote_ready=true` only when confidence is exactly `1.0` for observed traces (fallback remains required by default).

Backtest output shape:

```json
{
  "decision_key": "route.fix_ci",
  "total_observations": 6,
  "min_history": 3,
  "min_confidence": 0.8,
  "candidate_choice": "retry",
  "candidate_confidence": 0.833333,
  "predictions": 2,
  "abstentions": 4,
  "correct_predictions": 2,
  "accuracy": 1.0,
  "abstain_rate": 0.666667,
  "coverage_rate": 0.333333,
  "promote_ready": true
}
```

Interpretation in MVP:

- `predictions` and `coverage_rate` show how often a deterministic rule would actually fire.
- `abstentions` and `abstain_rate` quantify safe fallback usage when confidence is insufficient.
- `promote_ready=true` means the rule was perfect on predicted samples; fallback still remains mandatory in MVP.

Promotion output shape:

```json
{
  "promoted": true,
  "status": "promoted",
  "rule_id": "rule_123abc",
  "decision_key": "route.fix_ci",
  "candidate_choice": "retry",
  "min_accuracy": 1.0,
  "fallback_enabled": true,
  "metrics": {
    "accuracy": 1.0,
    "coverage_rate": 0.333333
  }
}
```

Interpretation in MVP:

- Promotion uses backtest metrics as evidence and refuses promotion when thresholds are not met.
- `fallback_enabled` is always true for promoted rules in MVP.
- Use `agentos rules list` to review promoted rule snapshots and stored metrics before any runtime wiring.

## QA / review and test coverage

Recommended local QA sequence:

```bash
python -m unittest -v
coverage run -m unittest
coverage report -m
```

Quality gates for MVP implementation work:

- Include automated tests for every behavior change.
- Keep touched-module coverage high (target: >=85%).
- Review CLI examples against the current command behavior before merging.

## Contributing

Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before opening issues or pull requests.
For future implementations, automated tests are mandatory and coverage should stay high (target: >= 85% on touched modules).

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).
