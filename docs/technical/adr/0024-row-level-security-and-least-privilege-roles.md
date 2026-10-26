---
type: reference
status: accepted
date: 2026-10-23
deciders: "@rahul-trip"
introduced_in: f3c4564 (migration 0009)
---

# 0024. Row-level security and three least-privilege Postgres roles

## Context

Phase 6a makes one deployment serve every customer's workspace. Application code already scopes every query by `workspace_id` ([0011](0011-operator-input-wins.md) and the layer rules), but application code scoping a query is not a tenant-isolation boundary — a bug, a forgotten filter in one new repository method, or a raw SQL script run by hand, bypasses it silently. The isolation needs to hold even when the application is wrong.

## Decision

Enable Postgres row-level security on every tenant table, enforced by the database itself, not by application discipline. Two roles are created by migration 0009, both `NOLOGIN` (a human adds the password and `LOGIN` once, out of band): `outbound_app`, with a single policy (`tenant_rows`) keyed on `current_setting('app.workspace_id')`, used by the API and worker for all day-to-day tenant work; and `outbound_platform`, read-only across every tenant table, used only by the scheduler and the admin console. `app.workspace_id` is set per-transaction (`SET LOCAL`, via a SQLAlchemy `after_begin` listener), never per-session, since a pooled connection serves many workspaces over its lifetime. A startup self-check (`outbound/db/isolation.py`) refuses to run `serve`/`worker` in production if the connected role is a superuser, `BYPASSRLS`, or a tenant-table owner (owners are exempt from RLS entirely), or if `anon`/`authenticated` — Supabase's Data API roles — still hold any grant.

## Consequences

- **Good:** a bug that forgets to filter by `workspace_id` fails closed — the database returns no rows rather than another tenant's rows. Foreign-key checks (migration 0007, composite keys) still work even if RLS itself is ever misconfigured, since FK checks run independent of RLS.
- **Bad:** three roles and two Postgres connection strings (`DATABASE_URL`, `PLATFORM_DATABASE_URL`) to configure correctly in every environment; a role created without `LOGIN` must be given a password and `LOGIN` manually once in Supabase, which is a step a deploy runbook, not a migration, must get right.
- **Follow-ups:** `FORCE ROW LEVEL SECURITY` is deliberately not set (the owner role still needs to run migrations and seed data unfiltered); the startup self-check substitutes for it in production.

## Alternatives considered

| Option | Why not |
|---|---|
| Rely on application-level `workspace_id` filtering only | Already the case pre-6a; does not hold if a query is wrong, and cannot be independently verified by a test that patches scoping out |
| `FORCE ROW LEVEL SECURITY` and no owner exemption | Would need a fourth role just for migrations, and Alembic's own tooling does not expect to run as a non-owner role |

## Evidence in the code

- `outbound/db/migrations/versions/0009_row_level_security.py`; `outbound/db/isolation.py`; `outbound/db/session.py::_set_workspace`.
- `tests/db/test_rls.py`.
