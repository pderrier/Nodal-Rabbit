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
→ trace decisions
→ detect repeated patterns
→ backtest deterministic rules
→ promote rules
→ run rule-first with fallback
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
- decision traces,
- outcome tracking,
- compilation candidates,
- backtesting,
- deterministic promotion,
- rule-first runtime,
- fallback to existing process.

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
script:
  - pip install agentos
  - agentos wrap \
      --intent "$AGENTOS_INTENT" \
      --source gitlab-ci \
      --run-id "$CI_PIPELINE_ID-$CI_JOB_ID" \
      --artifact-dir agentos-artifacts \
      -- ./scripts/run-codex-investigation.sh
```

Invariant: wrapper integration must not require rewriting the underlying script.

---

## 4) Reproducible intent and compilation candidacy

A decision is a compilation candidate only if all are true:
1. repeated pattern exists,
2. inputs are stable or fingerprintable,
3. outputs are identical or compatible,
4. outcomes are mostly successful,
5. risk is low/bounded,
6. generated rule can abstain safely,
7. fallback remains available.

Rule quality preference order:
1. high precision,
2. safe abstention,
3. explicit evidence,
4. low risk,
5. fallback compatibility.

Do not optimize for broad matching in MVP.

---

## 5) Compilation maturity levels

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

---

## 9) Required MVP CLI surface

### 9.1 Wrapping

```bash
agentos wrap --intent <intent> -- <command...>
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

## 10) Candidate detection and backtest contracts

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

## 11) First vertical slice (must be demo-ready)

Scenario:
1. Existing script simulates headless agent.
2. `agentos wrap` captures run.
3. Script optionally records structured decision.
4. Repetition generates candidate.
5. Candidate backtested.
6. Candidate promoted.
7. Future run uses rule-first.
8. Existing script remains fallback by default.

Demo commands:

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --artifact-dir .agentos/artifacts \
  -- examples/gitlab-ci/run-existing-agent.sh
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
  -- examples/gitlab-ci/run-existing-agent.sh
```

Expected outcomes:
- rule applied when matching,
- deterministic decision recorded,
- wrapped script still executes by default,
- fallback invariant preserved.

---

## 12) AGENTS.md directives for implementation agents

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

---

## 13) Acceptance criteria for MVP v0.3

MVP is successful only if:
1. Existing scripts run unchanged under `agentos wrap`.
2. Runs/events/decisions/outcomes are queryable locally.
3. Repeated patterns produce compilation candidates.
4. Backtest metrics are computed and persisted.
5. Promotion is explicit and versioned.
6. `--rule-first` works with fallback-on by default.
7. Safety behavior matches declared non-sandbox scope.

MVP is not successful if:
- users must rewrite workflows,
- AgentOS replaces Codex/Claude instead of wrapping,
- orchestration is built before compilation proof,
- fallback is removed by default,
- sandboxing is claimed but absent.

---


## 14) Reference repository layout (MVP target)

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

## 15) Changelog (v0.2 → v0.3)

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

## 16) Anti-drift checklist (required in PR reviews)

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
→ trace decisions
→ detect repeated patterns
→ backtest deterministic rules
→ promote rules
→ run rule-first with fallback
```
