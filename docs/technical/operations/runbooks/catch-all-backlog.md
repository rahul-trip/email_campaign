---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Leads pile up held as catch-all

| | |
|---|---|
| **Severity** | SEV-3 |
| **Impact** | Leads wait in `held` (`catch_all_resolving` or `catch_all_unverified`) and never get an email. |
| **Signals** | Needs attention screen; `outbound status` shows many catch-all holds |
| **Related** | [email stage](../../lld/stage-email.md), [Scrubby](../../integrations/scrubby.md), [R-02](../../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```sql
SELECT hold_reason, count(*) FROM companies
WHERE workspace_id = :ws AND status = 'held' GROUP BY 1;
```

| Reason | Cause |
|---|---|
| `catch_all_resolving` | Waiting for an asynchronous resolver (Scrubby, 24–72 h). The poller runs only from `tick` (R-02), and Scrubby is unproven live |
| `catch_all_unverified` | No resolver configured, or it could not decide, and `safe_to_send_only` is on |

## 2. Contain

—

## 3. Fix

- Make sure `tick` runs ([tick not running](tick-not-running.md)).
- Consider `CATCH_ALL_RESOLVER=enrichley` (answers at once) while Scrubby is unconfirmed.
- For a lead where the operator knows the address is good: **Skip the check** on the address, with a reason. Approval will ask for an acknowledgement.
- Or **Write to someone else** at the company, or add a person with a known address.

## 4. Verify

Held counts fall; resolved leads move to `email_ready`.

## 5. Follow up

Track the catch-all share in the quality report.
