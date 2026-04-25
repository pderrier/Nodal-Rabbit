# AgentOS coding rules (MVP v0)

AgentOS is not a coding agent.
AgentOS is not a chatbot.
AgentOS is not a full workflow orchestrator in v0.

MVP priorities:
1. Wrap existing processes.
2. Trace runs and decisions.
3. Record outcomes.
4. Detect repeated patterns.
5. Backtest deterministic rules.
6. Promote rules with fallback preserved.

Required implementation behavior:
- Preserve wrapper-first adoption.
- Do not force users to rewrite existing automation.
- Keep fallback by default.
- Every compiled rule must abstain when uncertain.
- Every promoted rule must include backtest metrics.
- Prefer simple local primitives (CLI, SQLite, JSONL, filesystem artifacts).
- Every implementation change must include automated tests and maintain high coverage (target: >=85% on touched modules).

Prohibited drift:
- Do not build a coding agent.
- Do not build a chatbot.
- Do not build a full orchestrator in MVP.
- Do not claim sandboxing in MVP.
- Do not hide safety constraints only in prompts.
- Do not add heavy dependencies without strong justification.

## Decision capture rule

AgentOS must never claim to capture hidden LLM reasoning or hidden LLM decisions.

`agentos wrap` captures process execution.
LLM decisions become AgentOS decisions only if explicitly declared through:
- decision files,
- stdout markers,
- CLI/SDK instrumentation.

Only valid declared decisions with associated outcomes may become compilation candidates.

Passive stdout parsing may be used for debugging, but not for trusted compilation in MVP.
