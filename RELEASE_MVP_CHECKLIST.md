# AgentOS MVP Release Checklist

Date: 2026-04-25
Scope: MVP v0 release readiness

## 1) Delivery artifacts

- [x] End-to-end MVP vertical slice documented (`VERTICAL_SLICE_MVP_RELEASE.md`).
- [x] Release anti-drift checklist available in repository.
- [x] Final docs reference canonical MVP spec + roadmap + release artifacts.
- [x] Executable checklist command available: `python -m agentos release checklist [--strict] [--json]`.

## 2) Product/technical invariants (anti-drift)

- [x] One-command wrapper adoption for existing scripts/jobs is preserved.
- [x] Codex/Claude/scripts are wrapped, not replaced.
- [x] No orchestration platform behavior introduced before proving compile loop value.
- [x] Fallback remains enabled by default.
- [x] Every promoted rule abstains safely when uncertain.
- [x] No unimplemented sandbox/security claims appear in docs/runtime.
- [x] No heavy framework integration added before wrapper-first success.
- [x] AgentOS is not turned into a chatbot/personal assistant.
- [x] Core loop is preserved exactly.

## 3) Test and quality gates

- [x] Unit + CLI integration tests pass locally.
- [x] Coverage on touched modules remains high (target >=85%).
- [x] End-to-end compile/promote/rule-first behavior is exercised by automated tests.
- [x] Automated gate evaluation is implemented in CLI (`release checklist`).

## 4) Runtime and data model checks

- [x] SQLite schema is initialized automatically on first run.
- [x] JSONL traces are written per run under `.agentos/runs/<run_id>/trace.jsonl`.
- [x] Decisions/outcomes are queryable and linked to runs.
- [x] Promoted/rejected rules persist evidence snapshots.

## 5) Release sign-off

- [x] MVP demonstrable in local + CI contexts.
- [x] README reflects implemented commands and release docs.
- [x] All open release blockers resolved or explicitly documented.

## Automated checklist behavior

`agentos release checklist` evaluates the release gates that can be verified automatically:

- release artifacts exist in repository root;
- runs include persisted trace path metadata;
- stored rules preserve fallback policy;
- minimum local evidence records (runs/decisions/outcomes) are present;
- README references implemented commands and release docs.

Use `--strict` to fail CI when any automatic gate returns `fail`.
