# AgentOS MVP Specification v0.3

Status: Draft for implementation planning (no code changes in this spec).

## 0) Scope and non-scope

AgentOS in MVP is **not**:
- a coding agent,
- a chatbot,
- a personal assistant,
- a replacement for Claude Code / Codex CLI / aider / OpenClaw,
- a replacement for MCP / GitLab CI / existing scripts,
- a workflow engine / orchestrator platform.

AgentOS in MVP **is**:
- a wrapper-first execution, trace, and compilation layer for existing headless agentic automation.

Core loop (must remain intact):

```text
wrap existing process
→ capture declared decisions
→ validate decisions and outcomes
→ detect repeated patterns
→ backtest deterministic rules
→ promote rules
→ run rule-first with fallback
```

Guiding constraints (MVP):

```text
Run capture is automatic.
Decision capture is declarative.
Compilation requires validated decisions and outcomes.
```

---

## 1) Product thesis and adoption contract

AgentOS is a progressive compiler for existing agentic automation.

Adoption contract:
1. Observe first.
2. Instrument second.
3. Compile third.
4. Orchestrate last.

Primary command:

```bash
agentos wrap --intent some.intent -- ./existing-agent-or-script.sh
```

Users must be able to keep:
- existing GitLab CI jobs,
- existing shell scripts,
- existing Codex/Claude headless prompts,
- existing MCP tools,
- existing Docker images,
- existing deployment model,
- existing agents.

AgentOS adds:
- run traces,
- declared decision traces,
- outcome tracking,
- compilation candidates,
- backtesting,
- deterministic promotion,
- rule-first runtime,
- fallback to existing process.

Decision honesty rule:

```text
AgentOS does not infer hidden LLM decisions.
It captures declared operational decisions through files, stdout markers, or explicit instrumentation.
```

---

## 2) System boundary and integrations

### 2.1 Do not reinvent existing agents

Treat Codex/Claude/aider/custom scripts/MCP-based tooling as opaque or semi-opaque workers.

AgentOS responsibilities:
- wrap,
- trace,
- record,
- compare,
- backtest,
- promote,
- fallback.

AgentOS must not attempt to become a better coding model runtime than specialized tools.

### 2.2 Boundary with OpenClaw

Boundary contract:

```text
OpenClaw decides what to ask for.
AgentOS decides how to execute safely and reproducibly.
Claude/Codex/custom scripts solve specialized tasks.
Tools perform actions.
Verifiers validate acceptance.
```

OpenClaw integration is optional. MVP must run via CLI and CI only.

### 2.3 Build vs integrate (MVP choices)

Preferred stack:
- CLI-first,
- local-first,
- SQLite,
- JSONL traces,
- filesystem artifacts,
- process wrapper,
- optional Python API,
- simple rule registry + backtesting.

Out of scope in MVP:
- Temporal runtime,
- LangGraph orchestration,
- new MCP protocol,
- new LLM framework,
- multi-agent orchestrator,
- web UI.

---

## 3) Compatibility with existing automation (hard requirement)

### Existing shell script

Before:

```bash
./run-agent.sh
```

With AgentOS:

```bash
agentos wrap --intent gitlab.fix_ci -- ./run-agent.sh
```

### Existing Codex prompt

Before:

```bash
codex exec "$PROMPT"
```

With AgentOS:

```bash
agentos wrap --intent repo.fix_bug -- codex exec "$PROMPT"
```

### Existing GitLab CI job

Before:

```yaml
script:
  - ./scripts/run-codex-investigation.sh
```

With AgentOS:

```yaml
investigation-agent:
  stage: investigate
  image: registry.example.com/agents/codex-runner:latest
  variables:
    AGENTOS_INTENT: "gitlab.fix_ci"
    AGENTOS_SOURCE: "gitlab-ci"
    AGENTOS_RUN_ID: "$CI_PIPELINE_ID-$CI_JOB_ID"
  script:
    - pip install agentos
    - mkdir -p agentos-artifacts
    - agentos wrap \
        --intent "$AGENTOS_INTENT" \
        --source "$AGENTOS_SOURCE" \
        --run-id "$AGENTOS_RUN_ID" \
        --artifact-dir agentos-artifacts \
        --decision-file agentos-artifacts/decisions.json \
        -- ./scripts/run-codex-investigation.sh
  artifacts:
    when: always
    paths:
      - agentos-artifacts/
```

Invariant: wrapper integration must not require rewriting the underlying script.

Wrapper contract:

```text
The wrapper captures runs. Decisions require a decision channel.
```

Note:

```text
The existing script can initially ignore AgentOS. In that case only the run is captured.
To make decisions compilable, the script should write `agentos-artifacts/decisions.json` or emit decision markers.
```

---

## 4) Wrapper promise and compilation candidacy

Correct capture model:

```text
agentos wrap alone captures:
- command
- run id
- intent label
- source metadata
- stdout/stderr
- exit code
- duration
- artifacts
- selected environment metadata

agentos wrap alone does NOT reliably capture:
- hidden LLM reasoning
- implicit LLM choices
- operational decisions unless they are declared
```

Replace any magical introspection framing with:

```text
AgentOS records what the process explicitly reports as an operational decision.
```

Compilation candidate baseline requirements:
1. decision was explicitly declared through a supported decision channel,
2. decision schema is valid,
3. output is structured and compilation_candidate=true,
4. associated outcome exists,
5. outcome is successful or explicitly accepted,
6. generated rule can abstain safely,
7. fallback remains available.

Warning:

```text
Passive run traces can be useful for debugging and later manual analysis, but they must not be used as trusted compilation data unless operational decisions have been explicitly declared and validated.
```

Rule quality preference order:
1. high precision,
2. safe abstention,
3. explicit evidence,
4. low risk,
5. fallback compatibility.

Do not optimize for broad matching in MVP.

---

## 5) Compilation maturity levels

MVP P0 priorities:
- P0 — Run capture via `agentos wrap`
- P0 — Decision capture through declared decision channels
- P0 — Decision schema validation
- P0 — Outcome capture
- P0 — Compilation only from validated declared decisions
- P0 — Backtesting and explicit promotion

- Level 0: LLM/process every time.
- Level 1: deterministic routing/classification before fallback.
- Level 2: scripted deterministic decision for repeated step.
- Level 3: compiled workflow path with fallback.
- Level 4: verified package with tests, metrics, rollback.

MVP scope: **Level 1 and Level 2 only**.

---

## 6) Fallback invariant (safety-critical)

Hard rule:

> Compiled rules must abstain when uncertain and must not remove fallback by default.

Default runtime behavior:

```text
rule match
  → record deterministic decision
  → still run existing process
```

Optional behavior (explicit opt-in only):

```text
rule match
  → skip fallback process
```

Required config guard:

```yaml
compiled_rules:
  allow_skip_fallback: false
```

---

## 7) Safety and honesty in MVP

`agentos wrap` in MVP does **not** sandbox processes. It only observes and records execution.

MVP safety baseline:
- no full env capture by default,
- redact TOKEN/SECRET/PASSWORD/KEY patterns,
- allow stdout capture disable,
- allow stderr capture disable,
- allow artifact exclusion,
- avoid secret logging,
- no destructive-action protection claims,
- no sandboxing claims.

Policy enforcement/sandboxing are future phases.

---

## 8) Data model and storage

Storage strategy:
- SQLite for indexes and queryable metadata,
- JSONL for run/event trace streams,
- filesystem for artifacts and compiled rule files.

Entities (minimum):
- `runs`: run metadata and lifecycle.
- `events`: append-only event timeline.
- `decisions`: structured decisions + fingerprints + candidate flag.
- `outcomes`: quality/acceptance result per run.
- `artifacts`: run-produced files and metadata.
- `compilation_candidates`: candidate rules from repeated decisions.
- `compiled_rules`: promoted deterministic rules + metrics + fallback policy.

Trace file:

```text
.agentos/runs/<run_id>/trace.jsonl
```

Implementation hint for source/validity tracking:

```text
DecisionSource:
- decision_file
- stdout_marker
- cli_record
- sdk_record
- passive_trace

DecisionValidity:
- valid
- invalid_schema
- missing_step_id
- missing_output
- missing_input_ref
- invalid_confidence
- missing_outcome
```

Trusted compilation queries should filter to declared sources (`decision_file`, `stdout_marker`, `cli_record`, `sdk_record`) and exclude `passive_trace`.

---

## 9) Decision capture channels

### Channel A — decision file (recommended)

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --decision-file agentos-artifacts/decisions.json \
  -- ./run-existing-agent.sh
```

```json
{
  "decisions": [
    {
      "step_id": "classify_failure",
      "decision_type": "llm",
      "input_refs": ["job-log.txt"],
      "output": {
        "failure_type": "eslint_unused_variable",
        "confidence": 0.94
      },
      "evidence": ["CI log contains no-unused-vars"],
      "compilation_candidate": true
    }
  ],
  "outcome": {
    "status": "success",
    "tests_passed": true,
    "patch_created": true
  }
}
```

Why channel A in P0:
- best compromise for existing Codex/Claude headless prompts,
- simple to adopt,
- robust enough for MVP,
- can be generated by script or by the LLM when prompt-enforced.

### Channel B — stdout markers

```text
===AGENTOS_DECISION_START===
{
  "step_id": "classify_failure",
  "decision_type": "llm",
  "input_refs": ["job-log.txt"],
  "output": {
    "failure_type": "eslint_unused_variable",
    "confidence": 0.94
  },
  "evidence": ["CI log contains no-unused-vars"],
  "compilation_candidate": true
}
===AGENTOS_DECISION_END===
```

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --parse-decision-markers \
  -- ./run-existing-agent.sh
```

Use when process cannot write files. This is less robust than a decision file, but still requires schema validation before compilation.

### Channel C — explicit CLI/SDK instrumentation

```bash
agentos decision record \
  --step classify_failure \
  --type llm \
  --input-file job-log.txt \
  --output-file classification.json \
  --candidate true
```

```python
from agentos import decision

decision.record(
    step_id="classify_failure",
    decision_type="llm",
    input_ref="job-log.txt",
    output={
        "failure_type": "eslint_unused_variable",
        "confidence": 0.94,
        "evidence": ["CI log contains no-unused-vars"],
    },
    compilation_candidate=True,
)
```

Most reliable mechanism; best for Python/Node scripts; still optional for zero-rewrite adoption.

---

## 10) Decision validation

A declared decision is valid only if:

```text
- JSON/schema is valid
- `step_id` is present
- `decision_type` is one of: rule, llm, human, script, verifier
- `output` is structured
- confidence, if present, is between 0 and 1
- input_refs or input_fingerprint is present when applicable
- evidence is present or explicitly empty
- compilation_candidate is boolean
```

Invalid decisions must be stored as raw artifacts or invalid decision records, visible in traces, and excluded from compilation candidates.

Hard rule:

```text
Only valid declared decisions can become compilation candidates.
```

---

## 11) Outcome capture

Supported methods:

### Outcome in decision file

```json
{
  "outcome": {
    "status": "success",
    "tests_passed": true,
    "patch_created": true,
    "summary": "Patch fixed eslint failure"
  }
}
```

### Outcome CLI

```bash
agentos outcome record \
  --status success \
  --tests-passed \
  --summary "Patch fixed eslint failure"
```

```text
Without outcome data, AgentOS can know that a decision was made, but not whether it was a good decision.
Therefore, decisions without outcome can be stored and inspected, but should not be promoted automatically and should not count as high-confidence compilation examples.
```

---

## 12) Required MVP CLI surface

### 9.1 Wrapping

```bash
agentos wrap --intent <intent> --decision-file <path> -- <command...>
agentos wrap --intent <intent> --parse-decision-markers -- <command...>
```

Options required in MVP:
- `--intent`
- `--source`
- `--run-id`
- `--config`
- `--artifact-dir`
- `--workspace`
- `--capture-stdout`
- `--capture-stderr`
- `--redact-env`
- `--rule-first`
- `--decision-file <path>`
- `--parse-decision-markers`
- `--strict-decisions`
- `--allow-invalid-decisions`

Decision option behavior:

```text
--strict-decisions:
  fail the wrapper if a declared decision file exists but is invalid.

default:
  keep process result, store invalid decision as invalid, exclude from compilation.
```

### 9.2 Decision recording

```bash
agentos decision record \
  --run-id <run_id> \
  --step <step_id> \
  --type <rule|llm|human|script|verifier> \
  --input-file <path> \
  --output-file <path> \
  --candidate true
```

Implicit current run support:

```bash
AGENTOS_RUN_ID=<run_id>
```

### 9.3 Outcome recording

```bash
agentos outcome record \
  --run-id <run_id> \
  --status success \
  --summary "Patch fixed eslint failure"
```

Optional fields:
- `--tests-passed`
- `--human-accepted`
- `--patch-created`
- `--mr-created`
- `--failure-reason`

### 9.4 Inspection

```bash
agentos runs list
agentos runs show <run_id>
agentos runs trace <run_id>

agentos decisions list
agentos decisions list --intent gitlab.fix_ci
agentos decisions show <decision_id>
```

### 9.5 Compilation

```bash
agentos compile candidates
agentos compile show <candidate_id>
agentos compile backtest <candidate_id>
agentos compile promote <candidate_id>
agentos compile reject <candidate_id>
```

---

## 13) Candidate detection and backtest contracts

Compilation candidates must be built from:
- declared decisions,
- valid decision schemas,
- associated outcomes,
- successful or explicitly accepted results.

Hard rule:

```text
Passive stdout/stderr inference must not create trusted compilation candidates in MVP.
```

Candidate detection must ignore:
- invalid decisions,
- decisions without output schema,
- decisions without associated outcome,
- decisions marked `compilation_candidate=false`,
- decisions from failed runs unless explicitly configured.

Trusted candidate query contract:

```text
source in decision_file/stdout_marker/cli_record/sdk_record
validity = valid
compilation_candidate = true
outcome.status in success/accepted
```

Default candidate detection thresholds (configurable):

```yaml
candidate_detection:
  min_examples: 5
  min_same_output_ratio: 0.8
  min_success_ratio: 0.8
```

Backtest output metrics required:
- `cases_total`
- `cases_matched`
- `cases_abstained`
- `correct_matches`
- `false_positives`
- `false_negatives`
- `accuracy_on_matched`
- `coverage`
- `success_rate_on_matched`

Promotion gates (default, configurable):

```yaml
promotion:
  min_cases: 10
  min_accuracy_on_matched: 0.95
  max_false_positive_rate: 0.03
  min_coverage: 0.3
```

No auto-promotion in MVP.

---

## 14) First vertical slice (must be demo-ready)

Scenario:
1. Existing script is run through `agentos wrap`.
2. Script writes `agentos-artifacts/decisions.json`.
3. AgentOS loads and validates the decision file.
4. AgentOS stores valid decisions and outcome.
5. Several sample runs produce similar declared decisions.
6. `agentos compile candidates` groups repeated valid successful decisions.
7. `agentos compile backtest <candidate_id>` tests a proposed rule against historical declared decisions.
8. `agentos compile promote <candidate_id>` promotes the rule.
9. Future `agentos wrap --rule-first` checks promoted rules first.
10. Existing process remains fallback by default.

Minimal example script (`run-existing-agent.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

mkdir -p agentos-artifacts

cat > agentos-artifacts/decisions.json <<'JSON'
{
  "decisions": [
    {
      "step_id": "classify_failure",
      "decision_type": "llm",
      "input_refs": ["job-log.txt"],
      "output": {
        "failure_type": "eslint_unused_variable",
        "confidence": 0.94
      },
      "evidence": ["CI log contains no-unused-vars"],
      "compilation_candidate": true
    }
  ],
  "outcome": {
    "status": "success",
    "tests_passed": true,
    "patch_created": true,
    "summary": "Patch fixed eslint failure"
  }
}
JSON

echo "Simulated existing agent completed"
```

Demo commands:

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --decision-file agentos-artifacts/decisions.json \
  -- ./run-existing-agent.sh
```

```bash
agentos compile candidates
agentos compile backtest <candidate_id>
agentos compile promote <candidate_id>
```

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --rule-first \
  --decision-file agentos-artifacts/decisions.json \
  -- ./run-existing-agent.sh
```

Expected outcomes:
- rule applied when matching,
- only validated declared decisions considered for trusted compilation,
- wrapped script still executes by default,
- fallback invariant preserved.

---

## 15) AGENTS.md directives for implementation agents

The repository AGENTS.md must instruct coding agents:
- Do not build a coding agent.
- Do not build a chatbot.
- Do not build a full orchestrator in v0.
- Do not force migration from existing automation.
- Preserve wrapper-first adoption.
- Preserve fallback invariant.
- Prefer simple local primitives.
- Every compiled rule must abstain when uncertain.
- Every promoted rule must include backtest metrics.
- Do not hide safety only in prompts.
- Do not claim sandboxing in MVP.
- Do not add heavy dependencies without strong justification.
- Never claim hidden LLM reasoning capture from wrapping alone.
- Treat decisions as compilable only when declared, validated, and outcome-linked.
- Allow passive traces for debugging only; never as trusted compilation input in MVP.

---

## 16) Acceptance criteria for MVP v0.3

MVP succeeds if:
- it wraps an existing process without requiring a rewrite,
- it captures run metadata automatically,
- it supports at least one declared decision channel,
- it validates declared decisions,
- it captures outcomes,
- it excludes invalid or undeclared decisions from compilation,
- it detects repeated valid successful decisions,
- it backtests a candidate rule,
- it promotes a rule explicitly,
- future runs can use promoted rules before fallback.

MVP fails if:
- it claims to capture hidden LLM decisions,
- it compiles from unstructured stdout guesses,
- it requires a full migration to a new workflow runtime,
- it replaces existing agents instead of wrapping them,
- it lacks a clear fallback path.

---


## 17) Reference repository layout (MVP target)

```text
agentos/
  AGENTS.md
  agentos_mvp_v0_3.md
  BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md

  src/agentos/
    cli/
      main.py
      wrap.py
      decision.py
      outcome.py
      compile.py
      runs.py

    core/
      ids.py
      time.py
      config.py
      errors.py

    storage/
      db.py
      migrations.py
      jsonl.py

    trace/
      recorder.py
      redaction.py
      fingerprints.py

    runtime/
      wrapper.py
      artifacts.py
      environment.py

    decisions/
      models.py
      recorder.py
      grouping.py

    outcomes/
      models.py
      recorder.py

    compiler/
      candidates.py
      rules.py
      generator.py
      backtest.py
      promote.py

    rules/
      registry.py
      result.py
      loader.py

  examples/gitlab-ci/
    run-existing-agent.sh
    agentos.yaml

  tests/
```

Roadmap and delivery sequence are maintained in `BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md`.

---

## 18) Changelog (v0.2 → v0.3)

- Consolidated MVP authority into `agentos_mvp_v0_3.md`; v0.2 content is superseded.
- Clarified strict non-goals (no coding agent/chatbot/workflow platform in MVP).
- Added explicit system boundary with OpenClaw and external agents.
- Added hard compatibility contract for shell, Codex, and GitLab CI wrapping.
- Introduced formal definition of “reproducible intent” and candidate criteria.
- Added compilation maturity levels and constrained MVP to Levels 1–2.
- Elevated fallback to a safety-critical invariant with explicit config guard.
- Strengthened safety/honesty language: no sandbox claim in MVP.
- Tightened CLI/data-model/backtest/promotion contracts to implementation-ready form.
- Added implementation-agent directives section for AGENTS.md alignment.
- Added explicit anti-drift checklist for PR and design review.

---

## 19) Anti-drift checklist (required in PR reviews)

- [ ] Does this keep one-command wrapper adoption for existing scripts/jobs?
- [ ] Does this wrap Codex/Claude/scripts instead of replacing them?
- [ ] Does this avoid building orchestration before proving compilation loop value?
- [ ] Does this preserve fallback by default?
- [ ] Does every rule abstain safely when uncertain?
- [ ] Does this avoid sandboxing/security claims that are not implemented?
- [ ] Does this avoid heavy framework integration before wrapper-first success?
- [ ] Does this avoid turning AgentOS into a personal assistant/chatbot?
- [ ] Does this preserve the core loop exactly?

```text
wrap existing process
→ capture declared decisions
→ validate decisions and outcomes
→ detect repeated patterns
→ backtest deterministic rules
→ promote rules
→ run rule-first with fallback
```
