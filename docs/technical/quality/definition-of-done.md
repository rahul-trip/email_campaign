---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Definition of done

A change is done when every item below that applies to it is true. The binding rules are in [CLAUDE.md](../../../CLAUDE.md). This page gathers them into one list, and the [pull request template](../../../.github/pull_request_template.md) turns it into a checklist.

## Every change

- [ ] It belongs to the current phase, on a branch named `phase-N/<task>`, and the PR is small enough to review.
- [ ] It keeps the binding architecture rules:
  - imports point down the layers;
  - vendor JSON stays in adapters;
  - every paid call is metered;
  - status changes only through the state machines;
  - no transaction across a network call;
  - every query scoped by `workspace_id`;
  - operator input wins;
  - safety gates are server-side;
  - LangGraph only in research and copy;
  - the schema changes only through Alembic.
- [ ] It adds nothing the phase does not need: no queue, event bus, plugin framework or speculative abstraction.
- [ ] It has tests at the lowest layer that proves it ([testing strategy](testing-strategy.md)); a bug fix starts with a failing test.
- [ ] Locally: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports && uv run pytest`.
- [ ] Data access changed → the suite also passes on Postgres (`uv run --with pgserver python -m scripts.pg_tests tests -q`, or CI).
- [ ] CI is green (all seven jobs).
- [ ] No secret, `.env`, `*.db`, `data/private/` or personal data in the diff (gitleaks passes).
- [ ] Logs use event names plus values, never names, addresses or email text ([logging](../lld/logging.md)).

## By kind of change

| If the change… | It is also done when… |
|---|---|
| Changes behaviour | The module's [LLD](../README.md#low-level-design) is updated; [PLAN.md](../../PLAN.md) too if a product rule changed |
| Changes data | An Alembic migration that follows the [migration rules](../data/migrations.md), tested up and down on both databases; [schema](../data/schema.md) and the migration log updated |
| Adds or changes a setting | [Configuration reference](../operations/configuration-reference.md) and `.env.example` updated |
| Adds or changes an endpoint | `npm run gen:api` committed; [API reference](../api/api-reference.md) updated |
| Adds or renames a log event | [Observability](../operations/observability.md) updated |
| Changes a screen, button or flow | `web2/src/tour/steps.ts` and `data-tour` marks updated; the manual's "Guided tour" section; `npm run build && npx playwright test` pass |
| Changes what the operator sees or does | [USER_MANUAL.md](../../USER_MANUAL.md) updated |
| Changes the deploy | [Deployment](../operations/deployment.md), [release and rollback](../operations/release-and-rollback.md), and the affected runbooks updated; rehearsed with `deploy/local-test.sh` |
| Adds a way to fail | A [runbook](../operations/runbooks/README.md) |
| Makes an architecturally significant decision | An [ADR](../adr/README.md) |
| Adds or changes a vendor | Its [integration page](../integrations/README.md); fixtures from its documentation; a live check recorded |
| Finds or fixes a defect | The [register](../tech-debt-and-risks.md) updated (closed entries move to "Closed", never deleted) |
| Corrects live data | A data-fix script that follows [data fixes](../operations/data-fixes.md), with its test |
| Closes a phase | Its gate record filled in; the status table in `docs/phases/README.md` updated; the [production readiness review](../operations/production-readiness.md) re-run; `last_verified` bumped on the pages that were checked |
