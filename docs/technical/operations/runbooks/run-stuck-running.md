---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# A run stays "running" for ever

| | |
|---|---|
| **Severity** | SEV-3 (SEV-2 if it hides real work) |
| **Impact** | The Runs screen shows a run that will never finish. Other runs still execute, but the stuck one confuses reports. |
| **Signals** | A run in `running` with no recent `stage_done` lines; it started before a deploy or a worker restart |
| **Related** | [R-05](../../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3), Phase 3b B3 |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --since 2h worker | grep '"run_id": "<id>"' | tail -5   # last activity for that run
oc ps -a                                                          # was the worker restarted?
```
A run is stuck if the worker restarted (deploy, crash, `oc restart`) while it was `running`. There is no stale-run recovery and no SIGTERM handling, so the run is never finished.

## 2. Contain

Nothing to contain. The leads it was processing are safe: each lead's status only changes in its own write, and the next run picks them up.

## 3. Fix

Mark the run failed by hand. This is a direct data change; runs have no events. Use the Supabase SQL editor, or `psql` through Doppler, and always filter by workspace:

```sql
UPDATE runs SET status = 'failed', finished_at = now(),
       counts = '{"error": "worker stopped; closed by hand"}'
WHERE id = '<run id>' AND status = 'running';
```

Then start a new run from the Runs screen if work is still due.

## 4. Verify

The Runs screen shows the run as failed; a new run executes and finishes.

## 5. Follow up

Until B2 and B3 are done, deploy only when no run is active.
