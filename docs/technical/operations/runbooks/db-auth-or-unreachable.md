---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# The database refuses the login, or cannot be reached

| | |
|---|---|
| **Severity** | SEV-2 |
| **Impact** | Every request fails with a 500; the worker cannot claim runs; `migrate` fails on deploy. `/api/health` still answers 200 (R-06). |
| **Signals** | `password authentication failed`; `Network is unreachable`; `could not translate host name`; `worker_error` lines; 500s with `unhandled_error` |
| **Related** | [Supabase](../../integrations/platform-supabase.md), [R-06](../../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --since 15m worker | grep -E '"worker_error"|OperationalError' | tail -5
oc run --rm --no-deps api outbound db current      # fails the same way if the DB is the problem
```

| Message | Cause |
|---|---|
| `password authentication failed` | Wrong password in `POSTGRES_URL`, still `[YOUR-PASSWORD]`, or not URL-encoded |
| `Network is unreachable` | The **direct** (IPv6) connection string is in use; use the session pooler on port 5432 |
| Timeouts, or `could not connect` | Supabase is down or paused; check the dashboard and the status page |
| `max clients reached` | See [database max clients](db-max-clients.md) |

## 2. Contain

Stop starting runs. Nothing is lost: leads wait in their status.

## 3. Fix

Correct `POSTGRES_URL` in Doppler `prd`: the session pooler URL, with the password URL-encoded and `?sslmode=require`. Then restart: `oc up -d` (or redeploy). If Supabase paused the project (free tier inactivity), resume it in the dashboard.

## 4. Verify

`oc run --rm --no-deps api outbound db current` prints the revision; the web app loads leads; `worker_error` stops.

## 5. Follow up

If the password was changed because it leaked, see [secret leaked](secret-leaked.md).
