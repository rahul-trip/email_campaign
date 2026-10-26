---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Migrations

The schema changes only through Alembic (binding rule 10 in [CLAUDE.md](../../../CLAUDE.md)). This page states the rules a migration must follow, records every migration so far, and explains how migrations interact with deploys and rollbacks. For the schema itself, see [schema](schema.md).

## Rules

A migration MUST:

1. **Be additive (expand/contract).** Add tables, nullable or defaulted columns, indexes, and wider `CHECK` lists. Never drop or rename a column, table or enum value in the same release that stops using it. Removing something is a later, separate release, after no deployed code uses it. This keeps the previous release able to run on the newer schema ([ADR 0018](../adr/0018-additive-only-migrations.md)).
2. **Work on SQLite and Postgres.** Use `op.batch_alter_table` for any `ALTER` (SQLite rebuilds the table). Give partial indexes both `sqlite_where` and `postgresql_where`.
3. **Name every constraint.** `CHECK` constraints are dropped and recreated **by name**, because SQLite's batch mode does not reliably carry an unnamed `CHECK` across the table copy (see 0003).
4. **Keep `CHECK` lists equal to the enums.** A value added to a `StrEnum` in `outbound/domain/enums.py` needs a migration that widens the matching `CHECK`. `tests/db/test_migrations.py::test_each_check_constraint_allows_exactly_the_values_of_its_enum` fails otherwise.
5. **Be frozen.** A migration spells out its values literally and imports nothing from the application, so later model changes cannot alter what an old revision builds. `0001_schema_v1.py` is the model for this.
6. **Have a downgrade that is safe or refuses.** A downgrade that would lose data or make something workable without a person's decision raises instead (0003 refuses while `unconfirmed` contacts exist). Downgrades are for development; production never downgrades (see "Rollback" below).
7. **Arrive in the same PR** as the model change, [schema.md](schema.md) (the table block and §7 "Value conventions"), and this page's log.
8. **Be tested up and down on both databases.** CI runs the suite on SQLite and Postgres 16. Locally: `uv run --with pgserver python -m scripts.pg_tests tests/db -q`.

Drafting one: `outbound.db.migrate.generate(url, message)` runs Alembic autogenerate from the models. Always review its output: autogenerate misses `CHECK` changes and partial indexes. Then make it frozen and literal by hand.

## Log

| Revision | Date | What it does | Kind | Downgrade |
|---|---|---|---|---|
| `0001_schema_v1` | 2026-10-17 | Creates the 17 tables of schema v1, with every enum as text plus a named `CHECK` | Create | Drops everything |
| `0002_live_touch_and_webhook_uniqueness` | 2026-10-18 | Replaces the unique `(company_id, contact_id, step)` on `messages` with the partial unique index `ux_messages_live_touch` (only live messages, not `cancelled` or `rejected`); adds `ux_import_batches_webhook` (one batch per webhook event); adds `uq_workspaces_name` | Relaxes one rule, adds two | Restores the old constraint (fails if live data now violates it) |
| `0003_unconfirmed_contacts` | 2026-10-20 | Widens `ck_contacts_contact_status` with `unconfirmed` | Widen `CHECK` | **Refuses** while any contact is `unconfirmed` |
| `0004_policy_skip` | 2026-10-21 | Adds `companies.policy_skip_from` (nullable) with `CHECK ck_companies_policy_stage` | Add column | Drops the column |
| `0005_verification_skipped` | 2026-10-21 | Adds `contact_emails.verification_skipped` (boolean, not null, default false) | Add column | Drops the column |

All five are compatible with the release before them: old code runs on the new schema. 0002 drops a constraint, but only a stricter one that old code never relied on to be absent.

## How migrations run

| Where | How |
|---|---|
| Development | `uv run outbound db upgrade` (and `db current`, `db downgrade`). Uses `DATABASE_URL`, `--database-url`, or the `DATABASE_BACKEND` switch |
| Tests | The session fixture in `tests/db/conftest.py` migrates a fresh database; `tests/db/test_migrations.py` checks upgrade, downgrade, re-upgrade, model parity and `CHECK` parity |
| Production | The `migrate` service in `deploy/compose.yml` runs `outbound db upgrade && outbound seed` before `api` and `worker` start, on every deploy. Both commands are idempotent |

`outbound/db/migrations/env.py` uses `render_as_batch=True`, `compare_type=True`, and no connection pool.

## Rollback

Production never runs `db downgrade`. Downgrades can drop data, and the CLI warns so. A failed deploy goes back to the previous release's code on the **current** schema, which rule 1 keeps compatible.

**Known defect.** The rollback in `deploy/remote-deploy.sh` restarts the previous release's whole stack, including its `migrate` service. That runs `db upgrade` with the old code, which does not know the newer revision, and stops with `Can't locate revision identified by '<rev>'`. `api` and `worker` wait for `migrate` to succeed, so the rollback leaves the app down. This was reproduced on 2026-10-21 ([R-01](../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down)). Until it is fixed, follow [the deploy-failed runbook](../operations/runbooks/deploy-failed-or-rollback.md).

## Checklist for a migration PR

- [ ] Additive, or the contract half of an earlier expand (say which)
- [ ] `batch_alter_table`; named constraints; `sqlite_where` and `postgresql_where` on partial indexes
- [ ] Literal values; no application imports
- [ ] Downgrade safe, or it refuses with a reason
- [ ] Enum and `CHECK` widened together
- [ ] [schema.md](schema.md) and this log updated
- [ ] `uv run pytest tests/db` on SQLite, plus Postgres (`scripts.pg_tests` or CI)

## Planned

- Phase 6 adds `users` and `workspace_members` (additive) and row-level security keyed on `workspace_id`: [phase-6-saas-ready.md](../../phases/phase-6-saas-ready.md).

## How to refresh this page

```bash
ls outbound/db/migrations/versions/
for f in outbound/db/migrations/versions/0*.py; do sed -n '1,/^"""$/p' "$f" | head -12; done
uv run outbound db current
uv run pytest tests/db/test_migrations.py -q
```
