# AgentOS MVP Release — Vertical Slice (End-to-End)

This document is the release-grade vertical slice for MVP v0.
It demonstrates the complete loop while preserving wrapper-first adoption and fallback-by-default behavior.

## Scope

The slice validates the exact MVP loop:

```text
wrap existing process
→ capture declared decisions
→ validate decisions and outcomes
→ detect repeated patterns
→ backtest deterministic rules
→ promote rules
→ run rule-first with fallback
```

## Prerequisites

- Python 3.11+
- Local repository checkout
- No external orchestrator/UI required

## Step 1 — Wrap an existing process (no rewrite)

```bash
python -m agentos wrap --intent demo.release.wrap -- echo "hello"
```

Expected: `run_id` returned with persisted run + trace.

## Step 2 — Record decisions and outcomes

Use `run_id` returned above.

```bash
python -m agentos decision record --run-id <run_id> --key route.fix_ci --candidate true --data-json '{"chosen":"retry"}'
python -m agentos decision record --run-id <run_id> --key route.fix_ci --candidate true --data-json '{"chosen":"retry"}'
python -m agentos decision record --run-id <run_id> --key route.fix_ci --candidate true --data-json '{"chosen":"retry"}'
python -m agentos decision record --run-id <run_id> --key route.fix_ci --candidate true --data-json '{"chosen":"retry"}'
python -m agentos decision record --run-id <run_id> --key route.fix_ci --candidate true --data-json '{"chosen":"retry"}'
python -m agentos outcome record --run-id <run_id> --status success --data-json '{"result":"green"}'
```

Expected: decisions are queryable via `agentos decision list` and linked to run/outcome.

## Step 3 — Detect repeated patterns

```bash
python -m agentos compile candidates --min-support 2 --limit 20
```

Expected: candidate row with confidence/abstention metrics.

## Step 4 — Backtest deterministic candidate

```bash
python -m agentos compile backtest --decision-key route.fix_ci --min-history 3 --min-confidence 0.8
```

Expected: persisted walk-forward metrics (`accuracy`, `coverage_rate`, `abstain_rate`).

## Step 5 — Promote or reject explicitly

```bash
python -m agentos compile promote --decision-key route.fix_ci --min-history 3 --min-confidence 0.8 --min-accuracy 1.0
```

Expected: promoted rule includes metrics snapshot and fallback policy preserved.

For explicit non-promotion:

```bash
python -m agentos compile reject --decision-key route.fix_ci --reason manual_review_required
```

## Step 6 — Execute rule-first runtime with fallback preserved

Observe mode (default-safe):

```bash
python -m agentos wrap --intent demo.release.rule_first --rule-first --decision-key route.fix_ci -- echo "fallback still executes"
```

Expected: rule can match, but process fallback still runs by default.

Opt-in skip mode:

```bash
python -m agentos wrap --intent demo.release.rule_first --rule-first --decision-key route.fix_ci --on-rule-match skip-fallback -- echo "skipped when matched"
```

Expected: fallback skipped only on explicit opt-in.

## Release acceptance criteria for this slice

- Existing command runs unchanged through `agentos wrap`.
- Decisions/outcomes are captured and inspectable.
- Candidate detection + backtest metrics are generated.
- Promotion evidence is persisted and explicit.
- Rule-first runtime keeps fallback by default.
- No sandboxing claim is introduced in runtime/docs.
