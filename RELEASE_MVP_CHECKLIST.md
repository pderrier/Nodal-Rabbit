# AgentOS MVP Release Checklist

Date: 2026-04-25
Scope: MVP v0 release readiness

## 1) Delivery artifacts

- [x] End-to-end MVP vertical slice documented (`VERTICAL_SLICE_MVP_RELEASE.md`).
- [x] Release anti-drift checklist available in repository.
- [x] Final docs reference canonical MVP spec + roadmap + release artifacts.
- [x] Executable checklist command available: `python -m agentos release checklist [--strict] [--json]`.

## 2) Product/technical invariants (anti-drift)

- [ ] One-command wrapper adoption for existing scripts/jobs is preserved.
- [ ] Codex/Claude/scripts are wrapped, not replaced.
- [ ] No orchestration platform behavior introduced before proving compile loop value.
- [ ] Fallback remains enabled by default.
- [ ] Every promoted rule abstains safely when uncertain.
- [ ] No unimplemented sandbox/security claims appear in docs/runtime.
- [ ] No heavy framework integration added before wrapper-first success.
- [ ] AgentOS is not turned into a chatbot/personal assistant.
- [ ] Core loop is preserved exactly.

## 3) Test and quality gates

- [ ] Unit + CLI integration tests pass locally.
- [ ] Coverage on touched modules remains high (target >=85%).
- [ ] End-to-end compile/promote/rule-first behavior is exercised by automated tests.
- [x] Automated gate evaluation is implemented in CLI (`release checklist`).

## 4) Runtime and data model checks

- [ ] SQLite schema is initialized automatically on first run.
- [ ] JSONL traces are written per run under `.agentos/runs/<run_id>/trace.jsonl`.
- [ ] Decisions/outcomes are queryable and linked to runs.
- [ ] Promoted/rejected rules persist evidence snapshots.

## 5) Release sign-off

- [ ] MVP demonstrable in local + CI contexts.
- [ ] README reflects implemented commands and release docs.
- [ ] All open release blockers resolved or explicitly documented.

## Automated checklist behavior

`agentos release checklist` evaluates the release gates that can be verified automatically:

- release artifacts exist in repository root;
- runs include persisted trace path metadata;
- stored rules preserve fallback policy;
- minimum local evidence records (runs/decisions/outcomes) are present.

Use `--strict` to fail CI when any automatic gate returns `fail`.
