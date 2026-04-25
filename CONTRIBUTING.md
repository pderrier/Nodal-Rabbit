# Contributing to AgentOS

Thanks for your interest in contributing.

This project is currently focused on **AgentOS MVP v0**. Contributions should preserve scope and avoid product drift.

## Ground rules

Before proposing changes, please align with:

- `agentos_mvp_v0_3.md` (canonical source of truth).
- `BACKLOG_MVP_PRIORISE_ROADMAP_6_SEMAINES.md` (execution priorities).

## MVP guardrails (must follow)

- Keep AgentOS wrapper-first.
- Do not force rewrites of existing automation.
- Keep fallback enabled by default.
- Ensure deterministic rules abstain when uncertain.
- Include backtest metrics for any promoted rule.
- Prefer local/simple primitives (CLI, SQLite, JSONL, filesystem artifacts).

## Out of scope for MVP

Please avoid contributions that move AgentOS into areas explicitly excluded in MVP:

- Coding-agent behavior.
- Chatbot/personal-assistant behavior.
- Full orchestration platform behavior.
- Claims of sandboxing in MVP.
- Heavy dependencies without strong justification.
- Building web UI / Temporal / LangGraph orchestration for MVP.

## How to contribute

1. Open an issue describing the problem and why it fits MVP scope.
2. If implementing a change, keep pull requests focused and small.
3. Reference which MVP section or roadmap item your change addresses.
4. Include validation notes (tests/checks/run examples) in the PR description.

## Pull request checklist

- [ ] Change is aligned with MVP scope and guardrails.
- [ ] Existing behavior remains wrapper-first.
- [ ] Fallback semantics are preserved.
- [ ] Documentation is updated where relevant.
- [ ] Tests/checks were run (or limitations are documented).
- [ ] New behavior is covered by automated tests.
- [ ] Test coverage remains high (target: **>= 85%** on touched modules).

## Test and coverage policy (mandatory for future implementations)

- Every future implementation PR must include or update automated tests.
- Changes without tests are considered incomplete unless a clear technical blocker is documented.
- Contributors should run coverage locally and keep coverage high, with a default target of **>= 85%** on touched modules.
- If coverage drops, the PR must explain why and include a remediation plan.

## Code and commit quality

- Prefer clear, minimal changes over broad refactors.
- Keep naming and behavior explicit.
- Write commit messages that explain intent and scope.

## Reporting issues

When filing an issue, include:

- Expected behavior.
- Actual behavior.
- Reproduction steps.
- Relevant logs/traces (redacted if needed).

## Questions

If unsure whether a contribution fits MVP scope, open an issue first to discuss.
