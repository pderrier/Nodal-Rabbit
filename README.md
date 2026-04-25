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

Quick local run:

```bash
python -m agentos wrap --intent demo.echo -- echo "hello"
python -m agentos decision record --run-id <run_id> --key route.fix_ci --data-json '{"chosen":"retry"}'
python -m agentos outcome record --run-id <run_id> --status success --data-json '{"ci_pipeline":"green"}'
python -m agentos runs list
```

## Contributing

Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before opening issues or pull requests.
For future implementations, automated tests are mandatory and coverage should stay high (target: >= 85% on touched modules).

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).
