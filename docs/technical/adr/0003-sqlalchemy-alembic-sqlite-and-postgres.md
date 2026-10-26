---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §3](../../PLAN.md#3-decisions-all-confirmed) decision 2; c3d3228 (#1); `DATABASE_BACKEND` in 1d58585
---

# 0003. SQLAlchemy 2 and Alembic over SQLite in development and Postgres in production

## Context

Development should need no services: a file database starts instantly and tests run in parallel without Docker. Production needs a managed, backed-up database that Phase 6 can extend with auth and row-level security (Supabase). The same schema and constraints must hold in both, or a bug found in production cannot be reproduced locally.

## Decision

One SQLAlchemy 2 model and one Alembic migration history serve both SQLite and Postgres. Closed value sets are `TEXT` columns with `CHECK` constraints that must equal the Python `StrEnum`s. JSON columns are JSONB on Postgres and JSON text on SQLite. Datetimes are timezone-aware UTC (`UtcDateTime` refuses naive values). The schema changes only through Alembic. `DATABASE_BACKEND` (`sqlite` or `postgres`) picks the database; an explicit `DATABASE_URL` wins.

## Consequences

- **Good:** no Docker for development; the full test suite runs on both databases in CI; constraints are real in both.
- **Bad:** only features both databases share can be used (no Postgres-only types, no `SKIP LOCKED` semantics on SQLite); SQLite `ALTER` needs Alembic batch mode; every migration must be tested on both.
- **Follow-ups:** binding rule 10 in [CLAUDE.md](../../../CLAUDE.md); the [migrations policy](../data/migrations.md).

## Alternatives considered

| Option | Why not |
|---|---|
| Postgres only, also in development | Docker or a local server for every contributor and test run |
| Raw SQL or a query builder | Repositories would re-implement mapping, versioning and dialect differences |
| The Supabase client library | Ties every query to one vendor and to HTTP; no transactions across tables |

## Evidence in the code

- `outbound/db/types.py` (`Json`, `UtcDateTime`, enum columns with `CHECK`); `outbound/db/migrations/env.py` (`render_as_batch=True`).
- `tests/db/test_constraints.py` (CHECK lists equal the enums); `tests/db/conftest.py` (`TEST_DATABASE_URL`).
- CI jobs `tests (SQLite)` and `tests (Postgres 16)` in `.github/workflows/ci.yml`.
