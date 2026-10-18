# Phase 1 — Schema and persistence

**Goal:** fix the data model in code and prove it on both target databases before any engine logic depends on it.
**Depends on:** nothing. Runs alongside Phase 0.
**Gate:**
- Alembic migrations run up and down on SQLite and on Postgres.
- Every uniqueness rule in [../SCHEMA.md](../SCHEMA.md) rejects a duplicate.
- The 10 rows from `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` import as companies.
- Running the import a second time changes nothing.

**Status (2026-10-17): code complete and verified locally on SQLite and on PostgreSQL 16.2.** The one open item is that the CI workflow is written but has not run yet, because there is no remote repository. See the [gate record](#gate-record).

## Scope

**In:**
- The `outbound/` package tooling.
- The domain core: enums, state machines, policies, IDs, money.
- SQLAlchemy models, the first migration, repositories and the unit of work.
- Seed data.
- The legacy xlsx import.
- The forget service.
- A minimal CLI for database tasks.

**Out:**
- Stages and the runner (Phase 2).
- The API (Phase 3).

## What changed from the plan

1. **Enum checks are generated, not typed.** The models use SQLAlchemy's non-native `Enum`, so each `CHECK` constraint is built from the matching `StrEnum`. The column is `VARCHAR(40)` rather than `TEXT`. A test confirms every constraint in the migrated database allows exactly its enum's values, which is stronger than the plan's "keep them in sync" test.
2. **The migration is frozen and self-contained.** Autogenerate's output imported application code and emitted each enum constraint twice (a naming clash on Postgres). It was rewritten by hand with plain `VARCHAR(40)` columns and one named `CHECK` each, so later changes to the models cannot alter what revision `0001` builds. A test confirms Alembic finds no differences between the migrated schema and the models.
3. **`BIGINT` for costs.** A 32-bit integer overflows at about $2,147 of micro-dollars.
4. **`StateMachine.check()` instead of `transition()` returning an event.** The domain only answers "is this move legal?". The repository makes the move and writes the event in the same transaction.
5. **Where a held lead resumes and which stages can fail it are fixed by tables.** `resume_status_for(hold_reason)` and `retry_status_for(stage)` live in the domain; `needs_operator` has no default.
6. **Forget does more than the plan said**: it cancels unsent messages and returns the draft ids for mailbox deletion, scrubs seven tables (see [SCHEMA §4](../SCHEMA.md#4-history-manual-input-concurrency)), and suppresses a company left with nobody to contact.
7. **A custom `UtcDateTime` type.** SQLite drops time zones, so the type restores UTC on read and refuses naive datetimes on write.
8. **The follow-up text and commonality columns of the old workbook are not imported as messages.** They were never drafted. The whole sheet row, including both, is kept in `import_rows.raw`.
9. **`scripts/pg_tests.py` runs the suite on a throwaway Postgres** (via `pgserver`) with no Docker, so the Postgres gate can be checked on a laptop.

## Tasks

### 1.1 Project skeleton and tooling — done

- [x] `pyproject.toml` managed with `uv` (`uv.lock` committed), Python 3.12, installable so `uv run outbound` works.
- [x] ruff (lint and format) and mypy (strict on `outbound.domain`).
- [x] `.pre-commit-config.yaml` running ruff and mypy. The hooks are not installed in your clone yet: run `uv run pre-commit install`.
- [x] `.github/workflows/ci.yml`: lint and types, tests on SQLite, and tests on a Postgres 16 service container. **Not yet run.**
- [x] `outbound/config.py` (pydantic-settings, with `DATABASE_URL`), `outbound/logging.py` (structlog JSON), and `outbound/bootstrap.py` (the composition root).

### 1.2 Domain core, no I/O — done

- [x] `ids.py` (UUIDv7), `money.py` (micro-dollars), `hashing.py`, `domains.py` (offline public-suffix lookup; free-mail and platform lists), `actors.py`.
- [x] `enums.py`: every closed value set.
- [x] `entities.py`: frozen snapshots that stages see instead of ORM rows.
- [x] `state_machines.py`: company, message, email and contact lifecycles as transition tables.
- [x] `policies.py` and `policy_seeds.py`: `decide_country_policy`, `check_send`, `is_safe_email_status` and `passes_fit_gate`, with the plan's default country policies.

**Tests (440):** every allowed transition is stated independently of the code's table and every other pair of states is refused; one test per ISO row of the compliance table.

### 1.3 Models and the first migration — done

- [x] `db/models.py`: the 17 tables, with generated enum checks, partial unique indexes for SQLite and Postgres, `version_id_col` on companies and messages, and JSON as `jsonb` on Postgres.
- [x] Alembic with `render_as_batch=True`; revision `0001` (frozen).

**Tests (31 migration + 22 constraint):** upgrade, downgrade and re-upgrade on a fresh database; `compare_metadata` finds nothing; all 25 enum constraints match their enums; every uniqueness rule, range check and foreign key refuses bad data when the repositories are bypassed.

### 1.4 Repositories, unit of work and forget — done

- [x] One small repository per aggregate, all scoped by `workspace_id`; `UnitOfWork` and `AdminUnitOfWork` (the one unscoped table).
- [x] Every status change goes through its state machine and writes an event in the same transaction.
- [x] The engine cannot overwrite a field in `manual_fields`; its attempt is recorded as an event instead.
- [x] A stale `row_version` raises `ConcurrencyConflict`, including a genuine two-session race.
- [x] `services/forget.py` and `db/repositories/erasure.py`.

**Tests (52 repository + 13 forget):** workspace isolation for reads and writes, the race, protected fields, the queue, caching and spend, and a scan of every text column of every table after a forget.

### 1.5 Seeds — done

- [x] `outbound seed` (5 tests): the default workspace (sender profile ported from the legacy examples, with the postal address and legal name blank), the default campaign, and the 11 country policies at version 1 with no reviewer.
- [x] Idempotent, and never overwrites a policy someone edited.

### 1.6 Legacy xlsx import — done

- [x] `outbound import-legacy-xlsx PATH`: one batch, one import row per sheet row (the whole row kept), and for each new company a company (`completed`), contact, primary address (`operator_given`), note and drafted message.
- [x] Idempotent; all rows in one transaction; rows with no usable domain are rejected with a reason.

### 1.7 CLI and viewing — done

- [x] `outbound db upgrade | downgrade | current`, `outbound seed`, `outbound import-legacy-xlsx`.
- [x] Datasette is a dev dependency: `uv run datasette outbound.db --immutable`.

## Observations for later phases

- Two of the ten imported leads are German organisations (EnergyAI Berlin and Fraunhofer Energy Alliance). The new policy blocks DE, so they would not be contacted today. They were drafted under the old process and are recorded as history only.
- Imported companies have no `country_code`; an operator or the research stage fills it in.
- The ten imported pitches run to about 200 words, against the new 50–85 word limit. They are history; the new copy stage replaces this style.

## Gate record

- **Date:** 2026-10-17.
- **Migrations up and down:** passed on SQLite and on PostgreSQL 16.2 (`uv run --with pgserver python -m scripts.pg_tests tests/db`). The CI run is still to come.
- **Uniqueness rules each reject a duplicate:** passed on both (`tests/db/test_constraints.py` and the repository tests).
- **Legacy import:** 10 companies, 10 contacts, 10 addresses, 10 drafted messages from the real workbook.
- **Second import:** 0 imported, 10 already there, nothing new created.
- **Test totals:** 831 passed and 1 skipped on SQLite (832 collected, including the 63 legacy tests); the 768 new-suite tests that apply passed on Postgres.
- **Checked by:**
- **CI run (link):**
