# ResearchPath repository guide

Use PowerShell 7 and the scripts in `scripts/` for setup, development and tests.

## Find the right entrypoint

- Machine-readable map: `project.manifest.json`
- API composition only: `apps/api/app/main.py`
- HTTP routes: `apps/api/app/api/routes/`
- Request DTOs and dependencies: `apps/api/app/api/`
- Domain/statistical orchestration: `apps/api/app/services/`
- Cross-language contracts: `specs/`
- R estimators: `engine/R/`
- Frontend API by domain: `apps/web/src/api/`
- Frontend types by domain: `apps/web/src/types/`
- Statistical methods and validation rules: `docs/02-统计方法与报告规范.md`, `docs/04-工程开发与验证.md`

## Architecture rules

- Services and engines must not import `app.api` or `app.main`.
- Route modules translate HTTP errors; statistical decisions stay in services/engines.
- `api.ts` and `types.ts` are facade entrypoints only. Add new code to focused modules.
- JSON Schema, Python contracts and TypeScript types must change together.
- A capability is visible only when its registry reports `executionAvailable=true`.
- Never write generated test data to the repository root. Runtime state belongs in ignored directories.

Use the smallest validation level that matches the change.

## Validation levels

- Read `docs/04-工程开发与验证.md` before repository-wide cleanup, performance work, security hardening or release preparation.
- Small changes use `scripts/harness.ps1 -Mode Quick`.
- Medium, single-feature changes use `scripts/harness.ps1 -Mode Targeted`: Quick runs once, then only explicitly selected module tests run.
- Cross-domain refactoring, statistical/contract foundations, shared security/runtime foundations and release candidates use `scripts/harness.ps1 -Mode Full` directly; do not run Quick separately first.
- Never raise coverage, type, bundle, performance or statistical tolerances merely to make a failing gate pass.
- Validate persisted paths, object identity and resource budgets before filesystem or database side effects.
- Stop only the object the user named: scans, processes, Codex pages and task archives are distinct lifecycle objects.

## Current-state documentation

- Public documentation describes the product as it exists now. Do not add PR numbers, internal ticket IDs, dated implementation diaries or migration narratives.
- Record durable behavior, supported boundaries and reproducible verification commands next to the relevant product, method, architecture or operations documentation.
- Keep temporary plans, logs, screenshots and review notes outside the repository.
- User-requested durable engineering change records and debt tracking belong in `docs/engineering/`; keep them separate from public product documentation and raw runtime logs.
- Cross-language contract changes must remain synchronized across JSON Schema, Python, TypeScript, R input and their tests.
