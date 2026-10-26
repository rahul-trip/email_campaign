---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Supabase Postgres

The production database is a Supabase Postgres project, reached from the VM over the internet ([ADR 0017](../adr/0017-supabase-session-pooler.md)). Nothing database-related runs on the VM.

## Connecting

| Option | Use? | Why |
|---|---|---|
| **Session pooler**, port 5432 | **Yes** | Reachable over IPv4; supports prepared statements |
| Direct connection | No | IPv6-only, out of reach of most GCP VMs (`Network is unreachable`) |
| Transaction pooler, port 6543 | No | Breaks the prepared statements psycopg uses |

- **URL:** `postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require`, stored in Doppler as `POSTGRES_URL`.
- **Driver:** the app rewrites `postgresql://` to the psycopg 3 driver (`outbound/db/session.py::normalise_url`).
- **Password:** URL-encode it if it contains `@ : / # ?`.
- **TLS:** `?sslmode=require` is what keeps the connection encrypted. The code does not enforce it ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)).
- **Schema:** the tables are created in the `public` schema by `outbound db upgrade`. Use a Supabase project of its own.

## Capacity

Small plans allow about **15 pooler clients in total**. Each process keeps up to `DATABASE_POOL_SIZE` connections (default 5, no overflow, pre-pinged, recycled every 300 s):

| Process | Connections |
|---|---|
| `api` | up to 5 |
| `worker` | up to 5 |
| `migrate` (only during deploys) | up to 5 (Alembic itself uses no pool) |
| Each `oc run … outbound …` one-off | up to 5 |

`api` + `worker` + `migrate` already reach the limit ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)). Lower `DATABASE_POOL_SIZE` in Doppler if Supabase reports `max clients reached` ([runbook](../operations/runbooks/db-max-clients.md)). See [capacity and limits](../operations/capacity-and-limits.md).

## Backups

Not documented or tested yet ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)). What Supabase provides (daily backups, point-in-time recovery, their retention) depends on the plan. See [backup and DR](../operations/backup-and-dr.md).

## When it fails

| Failure | Signal | Runbook |
|---|---|---|
| Wrong password or URL | `migrate` exits `password authentication failed` | [db-auth-or-unreachable](../operations/runbooks/db-auth-or-unreachable.md) |
| Direct connection used | `Network is unreachable` | Same |
| Pooler full | `max clients reached` | [db-max-clients](../operations/runbooks/db-max-clients.md) |
| Supabase down | Every request 500; worker logs `worker_error`; `/api/health` still 200 ([R-06](../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database)) | [db-auth-or-unreachable](../operations/runbooks/db-auth-or-unreachable.md) |

## Planned

Phase 6 uses Supabase auth and row-level security on `workspace_id`: [phase-6-saas-ready.md](../../phases/phase-6-saas-ready.md).
