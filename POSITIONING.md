# AgentOS — Positioning, Prior Art, Specificity and Rationale

> Working positioning document for the AgentOS open-source project.
> Purpose: clarify what AgentOS is, what already exists, what should be reused, what should not be reinvented, and what remains specific to the project.

---

## 1. Executive summary

AgentOS is a **wrapper-first trace and progressive compilation layer for existing agentic automation**.

It is not a coding agent, not a chatbot, not a personal assistant, and not a replacement for Claude Code, Codex CLI, MCP, Temporal, LangGraph, DSPy, BAML, Pydantic AI or existing CI systems.

The core thesis is:

> Existing headless agents and scripts often make repeated LLM-mediated decisions. Some of these decisions eventually become stable, recognizable and low-risk enough to be replaced by deterministic code. AgentOS exists to observe those decisions, trace their outcomes, detect repetition, backtest candidate rules, and promote safe deterministic paths while keeping the original process as fallback.

The central loop is:

```text
existing process
  → wrapped execution
  → trace
  → optional decision records
  → repeated patterns
  → candidate rule
  → historical backtest
  → explicit promotion
  → rule-first future run
  → existing process remains fallback
```

The project should optimize for:

```text
trivial integration
local-first adoption
CI compatibility
no mandatory migration
no lock-in
no reinvention of coding agents
progressive determinism
```

---

## 2. Problem statement

Modern headless agentic automation often looks like this:

```bash
codex exec "$PROMPT"
claude --print "$PROMPT"
./run-agent.sh
./investigate-ci-failure.sh
```

These scripts may run in:

```text
GitLab CI
GitHub Actions
Kubernetes Jobs
cron
local shell
internal platforms
OpenClaw-like assistant workflows
custom DevOps automations
```

The practical problem is not simply “how do we make the agent smarter?”

The practical problem is:

```text
Which parts of the process should stay LLM-mediated?
Which repeated decisions should become deterministic code?
How do we know a decision is stable enough to compile?
How do we backtest that rule before trusting it?
How do we keep fallback when the rule abstains?
How do we add this around existing automation without migrating everything?
```

Most existing tools solve execution, reasoning, coding, orchestration or structured output. AgentOS focuses on the missing operational layer:

> **progressive compilation of repeated agentic decisions into deterministic, tested rules around existing automation.**

---

## 3. Non-goals

AgentOS should not become:

```text
a coding agent
a Claude Code clone
a Codex CLI clone
an OpenClaw clone
a chatbot
a full workflow platform in MVP
a new MCP protocol
a new LLM framework
a new multi-agent framework
a replacement for GitLab CI / GitHub Actions
a heavy orchestration platform users must migrate to
```

If AgentOS requires users to rewrite their existing agentic jobs before getting value, it has failed its MVP positioning.

---

## 4. Target user

AgentOS is for engineers or teams who already have some form of headless automation:

```text
CI jobs running Codex/Claude/aider
scripts that call LLMs with prompts
internal incident investigation agents
DevOps automation jobs
OpenClaw-like personal automation
MCP-enabled tool workflows
scheduled agentic reports
```

These users do not primarily need a new agent.

They need a way to:

```text
wrap existing runs
record decisions
trace outcomes
detect repetition
compile safe rules
keep fallback
reduce LLM surface over time
```

---

## 5. Core positioning

### Short version

**AgentOS is a progressive compiler for existing agentic automation.**

### Longer version

AgentOS wraps existing headless agents, scripts and CI jobs, records what they decide and what happens, then helps promote repeated successful decision patterns into deterministic, tested, versioned rules.

It does not replace the existing process.

It adds an observation and compilation layer around it.

### One-line product promise

```text
Keep your existing agents. Add traces, backtests and deterministic rule-first execution over time.
```

### Recommended README wording

```markdown
AgentOS is a wrapper-first trace and progressive compilation layer for existing agentic automation.

It does not replace Claude Code, Codex CLI, aider, MCP, Temporal, LangGraph or your CI system.

It starts by wrapping your current scripts:

agentos wrap --intent gitlab.fix_ci -- ./run-existing-agent.sh

Then it records decisions, detects repeated patterns, backtests candidate rules, and promotes safe deterministic paths while keeping the existing process as fallback.
```

---

## 6. Prior art and existing tools

This section maps the relevant prior art and explains what AgentOS should reuse or avoid reinventing.

---

### 6.1 Claude Code

Claude Code is an agentic coding tool. It can read a codebase, edit files, run commands and integrate with development workflows.

AgentOS should not compete with Claude Code.

AgentOS should treat Claude Code as a supervised process.

```text
Claude Code answers:
“How do I solve this coding task?”

AgentOS answers:
“When should this task be run, how is it traced, what did it decide, can that decision be compiled, and what remains fallback?”
```

AgentOS should wrap Claude Code like this:

```bash
agentos wrap --intent repo.fix_bug -- claude --print "$PROMPT"
```

Or:

```bash
agentos wrap --intent gitlab.fix_ci -- ./run-claude-code-investigation.sh
```

**Reuse, do not reinvent:**

```text
codebase understanding
file editing
command running
coding task execution
developer-facing coding UX
```

**AgentOS-specific layer:**

```text
run trace
decision records
outcome tracking
rule candidates
backtesting
promotion
fallback
```

---

### 6.2 Codex CLI

Codex CLI is a local coding agent that can read, change and run code in a selected directory.

AgentOS should not compete with Codex CLI.

Codex should be an execution engine or opaque process.

Example:

```bash
agentos wrap --intent repo.fix_bug -- codex exec "$PROMPT"
```

AgentOS should not try to become “a better Codex.”

It should supervise Codex executions and progressively compile repeated decisions around them.

---

### 6.3 aider and other coding agents

Aider, custom repo agents and internal coding assistants occupy the same category as Codex/Claude Code from AgentOS’s perspective.

They are execution engines.

AgentOS should stay engine-agnostic.

```text
Engine examples:
- Codex CLI
- Claude Code
- aider
- custom Python scripts
- shell scripts
- MCP-enabled agents
- internal CI agents
```

AgentOS should not require a specific engine.

---

### 6.4 OpenClaw and personal assistants

OpenClaw-like systems are personal assistants or conversational shells.

They understand the user, personal context, intent, life workflow and UX.

AgentOS is lower-level.

```text
OpenClaw decides what to ask for.
AgentOS decides how to execute safely and reproducibly.
Codex/Claude/Alfred/custom scripts solve specialized tasks.
Tools perform real actions.
Verifiers decide whether results are acceptable.
```

OpenClaw can call AgentOS.

AgentOS should not become OpenClaw.

Example:

```text
User → OpenClaw:
“Check today’s priorities and portfolio risk.”

OpenClaw → AgentOS:
run intent personal.daily_review
run intent finance.portfolio_check

AgentOS:
wraps existing scripts/tools,
records decisions,
stores outcomes,
applies compiled rules if available,
keeps fallback.
```

OpenClaw is a shell/client.

AgentOS is a runtime and compilation layer.

---

### 6.5 MCP

The Model Context Protocol standardizes how applications expose tools, resources and context to AI systems.

AgentOS should not create a competing tool protocol.

MCP can be integrated later as a tool/capability layer.

For MVP, AgentOS does not need deep MCP support. It can simply wrap processes that already use MCP.

Future AgentOS integrations may include:

```text
MCP tool call tracing
MCP capability policies
MCP server inventory
MCP run metadata
```

But v0 should remain wrapper-first.

---

### 6.6 LangGraph

LangGraph provides graph-based, stateful agent orchestration with persistence, durable execution, human-in-the-loop support and long-running agent workflows.

AgentOS should not clone LangGraph.

LangGraph is relevant for future phases where AgentOS needs richer workflow execution.

For MVP, avoid making LangGraph a hard dependency if it complicates integration.

Possible future relationship:

```text
AgentOS wraps existing processes first.
Later, AgentOS can use LangGraph for advanced workflows or expose LangGraph runs as wrapped processes.
```

AgentOS-specific value remains:

```text
decision traces
compilation candidates
backtesting
promotion of deterministic rules
fallback policy
```

---

### 6.7 Temporal

Temporal provides durable workflow execution, retries, crash recovery, event history and replay-oriented deterministic workflows.

Temporal is highly relevant for production-grade durable agent systems.

AgentOS should not reimplement durable execution.

However, Temporal should not be required in MVP because it increases adoption complexity.

Future relationship:

```text
MVP:
local wrapper + SQLite + JSONL

Later:
Temporal adapter for durable/distributed execution
```

AgentOS can eventually treat a Temporal workflow as:

```text
a supervised execution backend
a source of event history
a durable runtime for AgentOS workflows
```

But AgentOS’s differentiator is still progressive compilation, not durable execution itself.

---

### 6.8 OpenAI Agents SDK

OpenAI Agents SDK provides agents, tools, guardrails, human review, state and tracing capabilities for agent applications.

AgentOS should not duplicate generic agent SDK behavior.

OpenAI Agents SDK may be useful when building agentic internals or integrations, but AgentOS’s MVP should not depend on it.

Reason:

```text
AgentOS must work with opaque existing processes, not only with processes built using a specific SDK.
```

AgentOS can later ingest or bridge traces from such SDKs, but its trace model should remain engine-agnostic.

---

### 6.9 BAML / Pydantic AI / JSON Schema

BAML and Pydantic AI solve structured LLM output and typed interfaces.

AgentOS should not invent a fragile structured output framework.

For MVP, AgentOS can use plain JSON files and Pydantic models internally.

Later, AgentOS can integrate with BAML or Pydantic AI for richer typed LLM calls.

Important distinction:

```text
BAML/Pydantic AI:
make individual LLM calls structured and reliable.

AgentOS:
observes repeated structured decisions and decides when to compile them into deterministic rules.
```

---

### 6.10 DSPy

DSPy focuses on programming language models rather than hand-writing prompts. It also includes optimizers that tune prompts or program parameters against metrics.

DSPy is related to AgentOS but not identical.

DSPy compilation generally optimizes an LM program.

AgentOS compilation means:

```text
promoting repeated LLM-mediated operational decisions into deterministic rules or code
```

Possible future use:

```text
Use DSPy to optimize remaining LLM fallback modules after AgentOS has collected historical traces.
```

But DSPy should not be required for MVP.

---

### 6.11 Semantic routers

Semantic routers classify inputs and route them to models, tools or workflows based on embeddings, examples or rules.

AgentOS may reuse semantic routing later.

But AgentOS is not “just a router.”

Routing is one possible decision type.

AgentOS’s specific value is:

```text
observe repeated routing/classification decisions
backtest deterministic alternatives
promote safe rules
keep fallback for abstentions
```

For MVP, simple deterministic grouping and rule matching is enough.

---

### 6.12 CI/CD platforms

GitLab CI, GitHub Actions and similar platforms already solve job execution, artifacts, logs, scheduling and permissions at CI level.

AgentOS should not replace CI.

AgentOS should plug into CI by changing one command:

```yaml
script:
  - agentos wrap --intent gitlab.fix_ci -- ./scripts/run-agent.sh
```

AgentOS artifacts should be CI artifacts.

AgentOS should be trivial to deploy inside existing CI images.

---

## 7. Prior art summary table

| Category | Existing examples | What they solve | AgentOS stance |
|---|---|---|---|
| Coding agents | Claude Code, Codex CLI, aider | Codebase understanding, edits, commands, tests | Wrap them, do not replace |
| Personal assistants | OpenClaw-like systems | User context, UX, personal goals | Sit below them as runtime |
| Tool protocols | MCP | Expose tools/resources to models | Integrate later, do not replace |
| Durable workflows | Temporal, LangGraph | Long-running execution, retry, resume | Integrate later, do not clone |
| Agent SDKs | OpenAI Agents SDK | Agents, tools, guardrails, traces | Optional integration, not core |
| Structured outputs | BAML, Pydantic AI, JSON Schema | Typed LLM calls | Reuse where needed |
| Prompt/program optimization | DSPy | Optimize LM programs/prompts | Possible future use |
| Semantic routing | semantic routers | Route inputs to tools/models | Useful component, not core |
| CI/CD | GitLab CI, GitHub Actions | Jobs, logs, artifacts, scheduling | Plug in with wrapper |
| AgentOS | This project | Compile repeated decisions into deterministic rules | Build this |

---

## 8. What is specific to AgentOS

AgentOS is specific because it combines four ideas that are usually separate:

```text
1. Wrapper-first adoption around existing automation.
2. Decision-level trace collection.
3. Historical backtesting of generated deterministic rules.
4. Progressive promotion from LLM/process-mediated behavior to rule-first execution with fallback.
```

The project’s distinctive question is:

> When should a repeated LLM-mediated decision stop being prompted and become code?

AgentOS should provide an operational answer:

```text
capture examples
measure stability
generate candidate
backtest candidate
promote explicitly
keep fallback
monitor future behavior
```

This is different from:

```text
“make the LLM more reliable”
“build a better agent”
“build a workflow engine”
“build a prompt framework”
“route to the right model”
```

AgentOS is about **reducing the surface of non-determinism over time**.

---

## 9. The concept of a reproducible intent

A reproducible intent is not merely a natural language instruction.

It is an observed operational pattern that can be recognized, tested and safely handled.

An intent or decision becomes compilation-worthy only if it satisfies most of these criteria:

```text
it appears repeatedly
it has stable inputs or recognizable fingerprints
it produces the same or compatible outputs
the outcomes are usually successful
the risk is low or bounded
the deterministic rule can abstain safely
fallback remains available
the rule can be tested against history
the rule can be versioned and rolled back
```

Examples:

```text
CI log contains eslint no-unused-vars
  → classify failure as eslint_unused_variable

CI log contains Cannot find module
  → classify failure as missing_dependency

User/GitLab event is failed pipeline with request to investigate
  → normalize intent as gitlab.fix_ci
```

Counterexamples:

```text
large ambiguous architecture refactor
security-sensitive auth change
unclear user intent with missing context
novel production incident
one-off creative planning task
```

These may remain LLM-mediated.

---

## 10. Compilation levels

AgentOS should formalize progressive compilation levels.

### Level 0 — Existing process every time

```text
AgentOS wraps and traces.
No deterministic decision yet.
```

### Level 1 — Deterministic routing/classification before fallback

```text
AgentOS applies a rule to classify or route.
Existing process still runs by default.
```

### Level 2 — Scripted decision for a repeated step

```text
A specific repeated LLM decision becomes a deterministic function.
The function can abstain.
Fallback remains available.
```

### Level 3 — Compiled workflow path

```text
Multiple decisions become a deterministic path.
Fallback handles out-of-distribution cases.
```

### Level 4 — Verified package

```text
Compiled rule/workflow includes tests, metrics, docs, rollback and versioning.
```

MVP should focus on Level 1 and early Level 2.

---

## 11. The fallback invariant

AgentOS must preserve fallback by default.

A compiled rule must:

```text
be deterministic
return evidence
abstain when uncertain
have backtest metrics
not remove fallback by default
```

Default rule-first behavior:

```text
rule matches
  → record deterministic decision
  → still run existing process
```

Optional behavior:

```text
rule matches
  → skip existing process
```

Skipping fallback must require explicit opt-in.

This prevents AgentOS from becoming dangerously overconfident.

---

## 12. Adoption model

AgentOS should support three adoption levels.

### Level 1 — Zero-rewrite wrapper

```bash
agentos wrap --intent gitlab.fix_ci -- ./run-agent.sh
```

The underlying script does not know AgentOS exists.

AgentOS captures:

```text
command
timing
exit code
stdout/stderr if enabled
artifact references
intent label
source metadata
```

### Level 2 — Metadata file

```bash
agentos wrap --config agentos.yaml -- ./run-agent.sh
```

Example:

```yaml
intent: gitlab.fix_ci
source: gitlab-ci

inputs:
  env:
    - CI_PROJECT_PATH
    - CI_PIPELINE_ID
    - CI_JOB_ID
    - CI_COMMIT_SHA

artifacts:
  collect:
    - agent-report.md
    - result.json
    - patches/*.diff

outcome:
  success_exit_codes: [0]

redaction:
  env_denylist:
    - "*TOKEN*"
    - "*SECRET*"
    - "*PASSWORD*"
```

### Level 3 — Instrumented decisions

Shell:

```bash
agentos decision record \
  --step classify_failure \
  --type llm \
  --input-file job-log.txt \
  --output-file classification.json \
  --candidate true
```

Python:

```python
from agentos import decision

decision.record(
    step_id="classify_failure",
    decision_type="llm",
    input_ref="job-log.txt",
    output={
        "failure_type": "eslint_unused_variable",
        "confidence": 0.94,
        "evidence": ["Matched no-unused-vars in CI log"],
    },
    compilation_candidate=True,
)
```

---

## 13. MVP architecture

The MVP architecture should remain small:

```text
existing process
  ↓
agentos wrap
  ↓
trace store
  ↓
decision/outcome store
  ↓
candidate detector
  ↓
backtester
  ↓
rule registry
  ↓
rule-first wrapper mode
```

Recommended MVP primitives:

```text
CLI
SQLite
JSONL trace files
filesystem artifacts
Python rule files
optional Python SDK
```

Avoid in MVP:

```text
distributed orchestration
Temporal hard dependency
LangGraph hard dependency
web dashboard
cloud control plane
deep sandboxing
multi-agent planner
```

---

## 14. Minimal CLI surface

```bash
agentos wrap --intent <intent> -- <command...>

agentos decision record \
  --run-id <run_id> \
  --step <step_id> \
  --type <rule|llm|human|script|verifier> \
  --input-file <path> \
  --output-file <path> \
  --candidate true

agentos outcome record \
  --run-id <run_id> \
  --status success \
  --summary "Patch fixed eslint failure"

agentos runs list
agentos runs show <run_id>
agentos runs trace <run_id>

agentos decisions list
agentos decisions show <decision_id>

agentos compile candidates
agentos compile show <candidate_id>
agentos compile backtest <candidate_id>
agentos compile promote <candidate_id>
agentos compile reject <candidate_id>
```

---

## 15. Minimal data model

Use SQLite for indexes and JSONL/filesystem for full trace/artifact storage.

Entities:

```text
runs
events
decisions
outcomes
artifacts
compilation_candidates
compiled_rules
```

### runs

```text
run_id
intent
source
command
cwd
status
exit_code
started_at
completed_at
artifact_dir
metadata_json
```

### events

```text
event_id
run_id
timestamp
event_type
payload_json
```

### decisions

```text
decision_id
run_id
step_id
decision_type
input_fingerprint
context_fingerprint
output_json
confidence
compilation_candidate
created_at
```

### outcomes

```text
outcome_id
run_id
status
tests_passed
human_accepted
patch_created
mr_created
summary
failure_reason
created_at
```

### compilation_candidates

```text
candidate_id
intent
step_id
candidate_type
source_decision_ids_json
proposed_rule_json
backtest_json
status
created_at
```

### compiled_rules

```text
rule_id
intent
step_id
rule_type
rule_source_path
metrics_json
fallback_policy_json
status
promoted_at
```

---

## 16. Build vs integrate rationale

### Build in MVP

```text
wrapper CLI
local trace store
decision recording
outcome recording
simple grouping of repeated decisions
candidate detection
backtesting
explicit promotion
rule-first mode
```

These are the core of AgentOS.

### Integrate later

```text
Temporal for durable/distributed execution
LangGraph for graph-based agent workflows
MCP for tool/capability introspection
BAML/Pydantic AI for rich typed LLM calls
DSPy for optimizing remaining LLM modules
OpenTelemetry for production observability
```

### Do not build

```text
coding agent
chat interface
personal assistant
new MCP equivalent
new CI system
generic multi-agent framework
```

---

## 17. Safety and honesty

MVP `agentos wrap` is not a sandbox.

It observes a process. It does not fully confine it.

The documentation must say this clearly.

MVP safety should include:

```text
no full environment capture by default
env allowlist or denylist
redaction of TOKEN/SECRET/PASSWORD/KEY-like values
optional stdout/stderr capture
artifact exclusion
no destructive-action claims
no sandboxing claims
```

Later phases can add:

```text
path policy
command policy
container sandboxing
secret scanning
human gates
diff policies
CI permission controls
```

---

## 18. First vertical slice

The first demo should prove the core loop.

### Scenario

An existing script simulates a headless agent that classifies a CI failure.

### Steps

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --artifact-dir .agentos/artifacts \
  -- examples/gitlab-ci/run-existing-agent.sh
```

The script optionally calls:

```bash
agentos decision record \
  --step classify_failure \
  --type llm \
  --output-file classification.json \
  --candidate true
```

After repeated examples:

```bash
agentos compile candidates
agentos compile backtest <candidate_id>
agentos compile promote <candidate_id>
```

Future run:

```bash
agentos wrap \
  --intent gitlab.fix_ci \
  --rule-first \
  -- examples/gitlab-ci/run-existing-agent.sh
```

Expected behavior:

```text
promoted rule is evaluated first
deterministic decision is recorded when rule matches
existing script still runs by default
fallback remains intact
```

---

## 19. Specificity compared to “compiled AI”

AgentOS is related to the broader idea of compiled AI: moving model-mediated behavior into deterministic executable artifacts when possible.

The AgentOS-specific angle is:

```text
compiled AI for existing operational agentic automation
wrapper-first
trace-driven
decision-level
historically backtested
fallback-preserving
CI-friendly
```

AgentOS does not require a greenfield workflow definition.

It starts from what already runs.

---

## 20. Rationale for wrapper-first MVP

A workflow-engine-first MVP would compete with existing tools and slow adoption.

A wrapper-first MVP lets users try AgentOS by changing one command.

This is important because the target users already have:

```text
scripts
CI jobs
Docker images
prompts
agents
logs
artifacts
```

The first value should be obtained without migration.

Therefore:

```text
observe before orchestrating
trace before controlling
compile before replacing
fallback before skipping
```

---

## 21. Risks

### Risk: becoming a coding agent

Mitigation:

```text
treat Codex/Claude/aider as engines
do not implement code editing intelligence
focus on trace/compile/fallback
```

### Risk: becoming a workflow platform too early

Mitigation:

```text
no full workflow engine in MVP
local wrapper first
Temporal/LangGraph later
```

### Risk: unsafe compiled rules

Mitigation:

```text
rules must abstain
rules must have backtests
promotion is explicit
fallback remains default
precision over coverage
```

### Risk: adoption friction

Mitigation:

```text
one-command wrapper
no required SDK
no required framework
CI examples
local-first storage
```

### Risk: overclaiming security

Mitigation:

```text
state clearly that MVP is not a sandbox
redact logs/env by default
future policy/sandboxing documented separately
```

---

## 22. Success criteria

AgentOS MVP is successful if:

```text
a user can wrap an existing agent script without modifying it
a script can optionally record structured decisions
runs and decisions are stored locally
repeated patterns are detected
candidate rules can be backtested
promotion is explicit
future runs can use rule-first mode
fallback remains available by default
integration into GitLab CI is trivial
```

AgentOS MVP fails if:

```text
users must rewrite existing automation
AgentOS becomes a coding agent
AgentOS requires a heavy orchestrator
fallback is removed
the compilation loop is missing
the project depends on a specific LLM provider or agent engine
```

---

## 23. Anti-drift checklist

Before adding any feature, ask:

```text
Does this help wrap existing automation?
Does this help trace decisions or outcomes?
Does this help detect repeated patterns?
Does this help backtest deterministic rules?
Does this preserve fallback?
Does this keep integration trivial?
```

If not, defer it.

Red flags:

```text
requires users to rewrite scripts
replaces Codex/Claude instead of wrapping them
builds orchestration before compilation
removes fallback
claims sandboxing without enforcing it
adds heavy dependencies before local wrapper works
turns AgentOS into a personal assistant
turns AgentOS into a chatbot
```

---

## 24. Source references and prior art links

These references are useful for context and should inform design, but AgentOS should not copy their scope.

### Coding agents

- Claude Code overview: https://code.claude.com/docs/en/overview
- Claude Code product page: https://www.anthropic.com/product/claude-code
- Codex CLI documentation: https://developers.openai.com/codex/cli
- OpenAI Codex repository: https://github.com/openai/codex

### Tool protocol

- MCP specification: https://modelcontextprotocol.io/specification/2025-11-25
- MCP tools concept: https://modelcontextprotocol.io/specification/draft/server/tools

### Durable workflows and agent orchestration

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph durable execution: https://docs.langchain.com/oss/python/langgraph/durable-execution
- LangGraph human-in-the-loop: https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- Temporal for AI: https://temporal.io/solutions/ai
- Temporal durable AI agent tutorial: https://learn.temporal.io/tutorials/ai/durable-ai-agent/
- Temporal dynamic AI agents article: https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal

### Agent SDKs and tracing

- OpenAI Agents SDK: https://developers.openai.com/api/docs/guides/agents
- OpenAI Agents SDK guardrails: https://openai.github.io/openai-agents-python/guardrails/
- OpenAI Agents SDK tracing: https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md

### Structured outputs and LLM programming

- DSPy documentation: https://dspy.ai/
- DSPy optimizers: https://dspy.ai/learn/optimization/optimizers/
- BAML documentation: https://docs.boundaryml.com/home
- BAML repository: https://github.com/boundaryml/baml

---

## 25. Final positioning statement

AgentOS is not the agent.

AgentOS is the layer that lets existing agents become progressively less mysterious.

It starts as a wrapper.

It records what happened.

It identifies decisions that repeat.

It backtests deterministic alternatives.

It promotes safe rules.

It keeps fallback.

Its purpose is not to make autonomy more magical.

Its purpose is to make repeated agentic work more reproducible, inspectable and eventually boring.
