## What and why

<!-- One paragraph: what changes, and the reason. Link the phase item (e.g. Phase 3b B7) or register entry (R-nn). -->

## How it was tested

<!-- Commands run and their result. Name new tests. -->

## Checklist

Code (see [CLAUDE.md](../CLAUDE.md)):

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports` pass
- [ ] `uv run pytest` passes (and on Postgres if data access changed)
- [ ] No secret, `.env`, `*.db` or personal data in the diff

Documentation (see [docs/technical/README.md](../docs/technical/README.md#keeping-the-pages-true)). Tick what applies, and delete the rest:

- [ ] Behaviour changed → the module's LLD in `docs/technical/lld/`, and [PLAN.md](../docs/PLAN.md) if a product rule changed
- [ ] Data changed → an Alembic migration, `docs/technical/data/schema.md`, `docs/technical/data/migrations.md`
- [ ] A setting was added or changed → `docs/technical/operations/configuration-reference.md` and `.env.example`
- [ ] An endpoint was added or changed → `npm run gen:api` (web2), `docs/technical/api/api-reference.md`
- [ ] A log event was added or renamed → `docs/technical/operations/observability.md`
- [ ] The deploy changed → `docs/technical/operations/deployment.md`, `release-and-rollback.md`, the affected runbooks
- [ ] A new way to fail → a runbook in `docs/technical/operations/runbooks/`
- [ ] An architecturally significant decision → an ADR in `docs/technical/adr/`
- [ ] A vendor was added or changed → its page in `docs/technical/integrations/`
- [ ] A screen, button or flow changed → `web2/src/tour/steps.ts` and the manual's "Guided tour" section
- [ ] The operator's steps changed → [USER_MANUAL.md](../docs/USER_MANUAL.md)
- [ ] A defect was found or fixed → `docs/technical/tech-debt-and-risks.md`
