---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# The database says too many clients

| | |
|---|---|
| **Severity** | SEV-2 |
| **Impact** | Requests and runs fail intermittently while the pool is full. |
| **Signals** | `max clients reached` or `remaining connection slots are reserved` in the logs |
| **Related** | [R-12](../../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler), [capacity and limits](../capacity-and-limits.md#database-connections) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

Count the processes: `api` and `worker` (5 connections each by default), plus `migrate` during a deploy, plus each `oc run` one-off, plus anything else using the database (the Supabase dashboard, a laptop on `DATABASE_BACKEND=postgres`).

## 2. Contain

Stop one-off commands and any laptop connected to production.

## 3. Fix

Set `DATABASE_POOL_SIZE=3` (or 2) in Doppler `prd`, then restart `api` and `worker` (`oc up -d --force-recreate api worker`, or redeploy). The engine's transactions are milliseconds long, so a small pool is enough for one operator.

## 4. Verify

No new `max clients` lines over a run; the Supabase dashboard's connection count stays under the limit.

## 5. Follow up

If it recurs, consider a larger Supabase plan.
