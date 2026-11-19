---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-19
applies_to: Phase 6 (ADR 0037)
---

# Work is waiting and the worker is not picking it up

| | |
|---|---|
| **Severity** | SEV-3 (SEV-2 if nothing runs for anyone) |
| **Impact** | Runs stay queued; new leads are not researched; drafts do not appear. |
| **Signals** | The admin Overview's **Worker** card says *Not responding*, *Never reported* or *Behind*; `worker_status` lines stop, or show `queued` growing or `overdue_ticks` above zero; a customer says their run has not started |
| **Related** | [ADR 0037](../../adr/0037-one-worker-process-leads-in-parallel.md), [the worker keeps restarting](worker-crash-loop.md), [a run stays running](run-stuck-running.md), [too many database clients](db-max-clients.md) |

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc ps                      # is `worker` up, or restarting?
oc logs --since 10m worker | grep -E 'worker_status|worker_error|run_claimed|run_failed' | tail -20
```

`worker_status` is written every minute: `queued`, `oldest_queued_seconds`, `busy` of `threads`, `overdue_ticks`. Read it like this:

- **No `worker_status` lines at all:** the worker is down or stuck. Go to [the worker keeps restarting](worker-crash-loop.md); if it is up but silent, restart it (step 2).
- **`busy` equals `threads`, `queued` grows:** the worker is working at its limit. See step 3.
- **`busy` is low, `queued` grows:** the kill switch is on (Admin → Settings → *Stop all runs*), or the workspace has no access (paused, suspended, access ended). A run never starts for those.
- **`worker_error` lines:** a database problem: [the database refuses the login](db-auth-or-unreachable.md) or [too many clients](db-max-clients.md).

## 2. Contain

`oc restart worker`. A run in flight is failed by the next worker's stale-run recovery once its heartbeat is 30 minutes old; its leads are picked up again by the next pass (nothing is lost).

## 3. Fix

If the worker is simply at its limit (the admin card says *Behind* for more than ten minutes at normal load):

1. Raise `WORKER_THREADS` (workspaces at once) or `WORKER_LEAD_CONCURRENCY` (leads in flight in one stage) in Doppler and restart the worker. Check the connection budget first: the worker's pool is `WORKER_DATABASE_POOL_SIZE` (8) and the pooler allows about 15 clients in all with the api ([deployment, connection budget](../deployment.md)). Transactions last milliseconds, so a smaller pool queues rather than fails (`DATABASE_POOL_TIMEOUT`), but a wait of seconds in the log (`QueuePool limit`) means the pool is too small for the threads.
2. If a vendor answers `429`, more concurrency makes it worse: lower `WORKER_LEAD_CONCURRENCY` ([vendor 429](vendor-429-or-outage.md)).
3. More than about 30 workspaces, or a second VM: this needs several worker processes and database leases, which are not built (ADR 0037).

## 4. Verify

The Worker card says *Keeping up*; `worker_status` shows `queued: 0`; the waiting run starts.

## 5. Follow up

Note the settings and the cause in the risks register if it recurs ([R-55](../../tech-debt-and-risks.md)).
