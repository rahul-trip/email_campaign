---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Paid calls are being refused, or spend is higher than expected

| | |
|---|---|
| **Severity** | SEV-2 if spend is unexpected; SEV-3 if a cap simply did its job |
| **Impact** | Leads fail at research, email or copy with a budget reason; or the cost report is higher than planned. |
| **Signals** | `provider_call_blocked` (WARNING); leads `failed` with "per-prospect budget used up"; Tavily `BudgetExceeded` (plan limit); the cost report |
| **Related** | [metering](../../lld/metering.md), [R-03](../../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5), [R-04](../../tech-debt-and-risks.md#r-04--p1--cost-the-budget-cap-prices-a-catch-all-submit-at-0), [R-10](../../tech-debt-and-risks.md#r-10--p1--budget-a-running-worker-does-not-see-budget-changes-b4) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --since 24h worker | grep '"provider_call_blocked"' | tail
oc run --rm --no-deps api outbound report cost --days 7
```
```sql
SELECT provider, operation, outcome, count(*), sum(cost_micro_usd)/1e6 AS usd
FROM provider_calls WHERE workspace_id = :ws AND created_at > now() - interval '1 day'
GROUP BY 1, 2, 3 ORDER BY usd DESC;
```

- A monthly cap (`MONTHLY_CAPS_MICRO_USD`) refuses all calls to one provider.
- The per-prospect ceiling refuses one lead.
- A vendor's own limit raises `BudgetExceeded` from the vendor (Tavily 432/433).

**Remember:** model calls are recorded at $0 without `LLM_PRICES` (R-03), so the real spend can be higher than the report.

## 2. Contain

If spend is unexpected, **stop the worker** (`oc stop worker`) and cancel queued runs. Check the vendor dashboards for the true spend.

## 3. Fix

- **Caps doing their job:** decide whether to raise them (`MONTHLY_CAPS_MICRO_USD` in Doppler, or the ceiling in Settings). Restart the worker afterwards: it reads the ceiling only at start (R-10).
- **Runaway:** find the loop (the same `request_hash` repeated, or one lead with many calls); fix it, then resume.
- **Set `LLM_PRICES`** if it is missing.

## 4. Verify

The cost report and the vendor dashboards agree; no unexpected `provider_call_blocked`.

## 5. Follow up

Record the actual spend in the incident note. Set vendor-side spending limits as a backstop.
