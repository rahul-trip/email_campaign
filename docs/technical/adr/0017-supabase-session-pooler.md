---
type: reference
status: accepted
date: 2026-10-19
deciders: "@rahul-trip"
introduced_in: 133fd06, 1d58585 (#11)
---

# 0017. Supabase Postgres through the session pooler, with psycopg 3 and a small pool

## Context

Phase 6 plans Supabase for auth and row-level security, so the production database starts there. Supabase's direct connection is IPv6-only, which most GCP VMs cannot reach. Its transaction pooler (port 6543) breaks the prepared statements psycopg uses. Small plans allow about 15 pooler clients in total.

## Decision

Production connects through the **session pooler** on port 5432 with `?sslmode=require`. Plain `postgresql://` URLs are rewritten to the psycopg 3 driver. Each process keeps a small pre-pinged pool (`DATABASE_POOL_SIZE`, default 5, no overflow, recycled every 300 s); migrations use no pool. `DATABASE_BACKEND=sqlite|postgres` switches a local install between a SQLite file and a Postgres URL; production compose pins `postgres`.

## Consequences

- **Good:** reachable from the VM over IPv4; prepared statements work; the same database Phase 6 extends.
- **Bad:** three processes at the default pool already use the whole small-plan limit ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)); TLS depends on the URL, not the code; the tables live in the `public` schema, so the project should be dedicated.
- **Follow-ups:** enforce TLS in code; size the pool to the plan; document backups ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)).

## Alternatives considered

| Option | Why not |
|---|---|
| A Postgres container on the VM | Backups, upgrades and disk on a shared VM become our job |
| Cloud SQL | More cost and setup; no path to the Phase 6 auth plan |
| The transaction pooler | Breaks psycopg's prepared statements |

## Evidence in the code

- `outbound/db/session.py` (`normalise_url`, `make_engine`); `outbound/config.py` (`database_backend`, `postgres_url`, `database_pool_size`, `_pick_database`); `deploy/compose.yml`.
