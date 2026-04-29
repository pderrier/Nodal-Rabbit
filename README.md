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

### Structured features for rule mining

A declared decision MAY include a `features` field — a flat dictionary of structured input attributes used for **feature-conditioned pattern mining**. This lets the rule extractor discover deterministic shortcuts like *"when `is_root=true` AND `has_mention=true`, the LLM always picks `feedback`"*, instead of just *"this decision_key is usually X"*.

Schema:
- `features` is an optional `dict[str, str | bool | int | float]`.
- Keys are non-empty strings. Values must be primitives (no nested dicts/lists).
- Decisions without features still work — they're handled by the (key-only) `patterns list`.

Example payload:

```json
{
  "step_id": "teams.classify_thread",
  "decision_type": "llm",
  "input_fingerprint": "sha256:...",
  "output": {"chosen": "feedback", "confidence": 0.95},
  "evidence": ["sender=Pierre Derrier", "channel=devops-claude"],
  "features": {
    "is_root": true,
    "is_reply": false,
    "has_mention": true,
    "sender_is_devops": true,
    "channel_id": "19:devops@thread.tacv2"
  },
  "compilation_candidate": true
}
```

Recording from the CLI:

```bash
agentos decision record \
  --run-id "$RUN_ID" \
  --key teams.classify_thread \
  --step teams.classify_thread \
  --type llm \
  --input-fingerprint "$FP" \
  --output-json '{"chosen":"feedback","confidence":0.95}' \
  --evidence-json '[]' \
  --features-json '{"is_root":true,"has_mention":true,"sender_is_devops":true}' \
  --candidate true
```

Mining feature-conditioned patterns:

```bash
# Bucket decisions by (decision_key, features) and report dominant choice per bucket.
# Output: one JSON line per (decision_key, features) combo with confirmed outcomes.
agentos patterns list --by-features --min-support 30

# Filter to a single decision_key:
agentos patterns list --by-features --decision-key teams.classify_thread --min-support 30
```

Feature-conditioned buckets with `confidence == 1.0` and high `support` are candidate deterministic rules.

### Decision-tree rule extraction

`patterns list --by-features` reports *exact-match* feature buckets — useful when every feature is observed and bucketed identically across runs. For a more powerful mining loop that finds *subset* rules (e.g. *"the LLM picks `feedback` whenever `is_root=true` AND `has_mention=true`, regardless of other features"*), AgentOS ships a greedy decision-tree extractor:

```bash
agentos rules extract \
  --decision-key teams.classify_thread \
  --min-coverage 20 \
  --min-precision 0.95 \
  --max-depth 4
```

The extractor:
1. Pulls all valid+candidate decisions for `--decision-key` with confirmed outcomes.
2. Builds a greedy CART-like decision tree on the structured `features` field, splitting on the highest Gini-impurity reduction at each node.
3. Walks high-precision leaves and emits one JSON-line rule proposal per qualifying leaf.

Output shape (one JSON object per line):

```json
{
  "decision_key": "teams.classify_thread",
  "predicate": [
    {"feature": "is_root", "op": "==", "value": true},
    {"feature": "has_mention", "op": "==", "value": true}
  ],
  "chosen": "feedback",
  "coverage": 47,
  "precision": 1.0,
  "support_total": 200,
  "support_share": 0.235
}
```

Rules are *proposals*, not promotions. Promotion to the rule store stays an explicit, human-reviewed step. The extractor is intentionally pure-Python with no ML dependency — Gini impurity, greedy single-feature splits, and equality-only predicates keep proposals simple and reviewable.

### Promoting an extracted rule

After reviewing the proposal, persist it with:

```bash
agentos rules promote-extracted \
  --decision-key teams.classify_thread \
  --predicate-json '[{"feature":"is_root","op":"==","value":true},
                     {"feature":"has_mention","op":"==","value":true}]' \
  --chosen feedback \
  --metrics-json '{"coverage":47,"precision":1.0,"support_total":200}'
```

Promoted feature-rules live in the same `promoted_rules` table as key-only rules — they are distinguished by the `predicate_json` column.

### Runtime: `check_rule()` SDK

Wrapped workers consume promoted rules via the runtime SDK *before* invoking their LLM/agent — if a rule matches, the worker returns the deterministic answer and skips the model call entirely:

```python
from agentos.runtime import check_rule

decision = check_rule("teams.classify_thread", {
    "is_root": True,
    "has_mention": True,
    "sender_is_devops": True,
})
if decision is not None:
    # Rule fired — skip the LLM, use the deterministic answer.
    return decision["chosen"]  # → "feedback"

# No rule matched — fall through to the model.
return llm_classify(...)
```

Returns `None` when no rule matches — the caller decides what fallback to invoke (LLM, manual flow, etc.). The most specific rule (longest predicate) wins ties, mirroring how a decision tree's deeper leaves carry more discriminating information.

This is the loop's payoff: when a feature combination has been observed enough times with a single deterministic outcome, the LLM call is replaced by a `dict` lookup. Cost drops, latency drops, accuracy rises (no model variance), and the fallback path is preserved by default.

## Concrete headless integration example (Claude Code + Codex CLI)

This example shows a wrapper-first integration where you keep your existing headless flows and only add explicit decision declarations.

### 1) Claude Code headless flow writes a decision file

`run-claude-headless.sh` (existing worker script):

```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p agentos-artifacts

# your existing headless invocation (placeholder)
claude-code --headless --input ci_failure.txt --output claude_output.json

# explicit declared decision for AgentOS compilation (not inferred)
cat > agentos-artifacts/decisions.json <<'JSON'
{
  "decisions": [
    {
      "step_id": "route.fix_ci",
      "decision_type": "llm",
      "input_refs": ["ci_failure.txt"],
      "output": {"chosen": "retry", "confidence": 0.93},
      "evidence": ["failure_signature:no-unused-vars"],
      "compilation_candidate": true
    }
  ],
  "outcome": {"status": "success", "pipeline": "green"}
}
JSON
```

Wrap it with AgentOS:

```bash
python -m agentos wrap \
  --intent ci.fix_with_claude \
  --decision-file agentos-artifacts/decisions.json \
  --strict-decisions \
  -- ./run-claude-headless.sh
```

`--strict-decisions` ensures malformed declarations fail fast instead of silently becoming trusted compilation input.

### 2) Codex CLI headless flow emits stdout decision markers

`run-codex-headless.sh` (existing worker script):

```bash
#!/usr/bin/env bash
set -euo pipefail

# your existing headless invocation (placeholder)
codex exec --task "fix failing CI"

# explicit declared decision marker for AgentOS ingestion
cat <<'MARKER'
===AGENTOS_DECISION_START===
{"step_id":"route.fix_ci","decision_type":"llm","input_refs":["ci_failure.txt"],"output":{"chosen":"retry","confidence":0.91},"evidence":["matched known flaky test pattern"],"compilation_candidate":true}
===AGENTOS_DECISION_END===
MARKER
```

Wrap it with AgentOS:

```bash
python -m agentos wrap \
  --intent ci.fix_with_codex \
  --parse-decision-markers \
  --strict-decisions \
  -- ./run-codex-headless.sh
```

If you do **not** want to modify model prompts, use a tiny adapter that converts existing tool output into a declaration file:

```bash
# adapter sketch (inside your existing script)
python extract_decision.py --from codex_output.json --to agentos-artifacts/decisions.json
python -m agentos wrap --intent ci.fix_with_codex --decision-file agentos-artifacts/decisions.json --strict-decisions -- ./run-codex-headless.sh
```

### 3) Do we need to modify headless prompts/scripts?

Short answer: **yes, minimally**—if you want trusted compilation candidates.

- AgentOS can capture full run traces/logs for debugging.
- But MVP intentionally does **not** trust passive log inference as a declared LLM decision.
- For compilation, the worker must emit an explicit declaration (decision file, stdout marker, CLI/SDK instrumentation).

Why: a free-form log line like `"I think retry might work"` is ambiguous and can be misread. MVP requires explicit structure to avoid guessing hidden reasoning.

Practical options:

1. **Prompt contract in headless mode** (ask Claude/Codex to emit one strict JSON object or marker block).
2. **Adapter script** (keep prompt unchanged, parse your tool output, then write `agentos-artifacts/decisions.json`).
3. **Direct instrumentation** (`agentos decision record ...`) from your existing script after each operational decision.

#### Prompt adaptation example (headless CLI task)

If your existing headless prompt is `"Fix the CI failure"`, adapt it to include a strict decision declaration contract:

```text
Task: Fix the CI failure.

After producing your normal output, you MUST emit exactly one AgentOS decision marker block:
===AGENTOS_DECISION_START===
{"step_id":"route.fix_ci","decision_type":"llm","input_refs":["ci_failure.txt"],"output":{"chosen":"retry|escalate|rollback","confidence":0.0},"evidence":["short evidence item"],"compilation_candidate":true}
===AGENTOS_DECISION_END===

Rules:
- output valid JSON (single object)
- confidence in [0,1]
- include at least one input reference
- do not include extra text inside the marker block
```

Minimal Claude Code headless shape:

```bash
claude-code --headless --prompt-file prompts/fix_ci_with_agentos_contract.txt
```

Minimal Codex CLI headless shape:

```bash
codex exec --task-file prompts/fix_ci_with_agentos_contract.txt
```

This preserves wrapper-first adoption: you keep the same worker and just tighten the output contract so AgentOS captures declared decisions safely.

### 4) Verification commands (prove decisions were declared, not guessed)

```bash
python -m agentos decision list --limit 20
python -m agentos runs trace <run_id>
```

For trusted compilation candidates in MVP, verify:

- `decision_source` is one of: `decision_file`, `stdout_marker`, `cli_record`, `sdk_record`.
- `decision_validity` is `valid`.
- `compilation_candidate` is `true`.
- an associated outcome is recorded for the run.

If a decision is only visible in passive logs and was never declared through one of the explicit channels above, treat it as debug-only and do not compile it.

## Repository contents

- `agentos_mvp_v0_3.md` — canonical MVP product/technical specification.
- `BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md` — six-week delivery roadmap and prioritized backlog.
- `POSITIONING.md` — positioning document covering prior art, non-goals, and project rationale.
- `VERTICAL_SLICE_MVP_RELEASE.md` — release-grade end-to-end MVP walkthrough.
- `RELEASE_MVP_CHECKLIST.md` — MVP release checklist and anti-drift gates.

## Getting started

This repository currently documents the MVP direction and delivery plan.

Suggested first steps:

1. Read the canonical spec in `agentos_mvp_v0_3.md`.
2. Review the roadmap in `BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md`.
3. Align implementation work with MVP scope and anti-drift constraints.
4. Read `POSITIONING.md` for positioning details and prior-art boundaries.



## Release readiness artifacts

For MVP release hardening and sign-off, use:

1. `VERTICAL_SLICE_MVP_RELEASE.md` for end-to-end execution proof.
2. `RELEASE_MVP_CHECKLIST.md` for anti-drift + quality gates.
3. `python -m agentos release checklist --json` for executable gate evaluation.

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
- Release gate command: `agentos release checklist` (supports `--strict` and `--json` for CI-friendly checks).

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
