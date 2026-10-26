---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Scheduled work is not happening

| | |
|---|---|
| **Severity** | SEV-3 (until live sending depends on it) |
| **Impact** | Failed leads are not retried; catch-all answers are not collected; sent emails are not recorded, so the quality report stays empty. |
| **Signals** | Leads in `failed` with a past `next_action_at`; `held` catch-all leads never released; no `sync` runs in the Runs list |
| **Related** | [R-02](../../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7), Phase 3b B7 |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```sql
SELECT count(*) FROM runs WHERE workspace_id = :ws AND kind = 'sync' AND created_at > now() - interval '1 day';
```
Nothing in production schedules `outbound tick` (R-02), so a count of zero is expected until it is set up.

## 2. Contain

—

## 3. Fix

Until the worker ticks by itself (B7), run it from the VM's crontab, as the deploy user. **To verify:** rehearse the line by hand first.

```cron
*/30 * * * * cd /opt/outbound/current && OUTBOUND_HOME=/opt/outbound RELEASE=$(basename "$(readlink /opt/outbound/current)") docker compose -p outbound -f deploy/compose.yml run --rm --no-deps api outbound tick --limit 50 >> /home/deploy/outbound-tick.log 2>&1
```

Be aware of three things:

- **Overlap.** A tick also runs the pipeline. If a worker run is in progress at the same time, both may work on the same leads. Writes are safe, but a vendor call can be paid twice (R-05). Choose a schedule away from the times runs are started.
- **Connections.** Each tick is one more database client while it runs ([database max clients](db-max-clients.md)).
- **Deploys.** Remove the cron line while you deploy, or accept that one tick may fail.

To run the retries alone, use `outbound retry`.

## 4. Verify

`sync` runs appear in the Runs list every 30 minutes; failed leads are retried; sent emails are matched.

## 5. Follow up

Remove the cron entry when B7 ships.
