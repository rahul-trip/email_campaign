---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Service levels

**Status: proposed.** No SLO has been agreed with the operator yet. These are the levels the product needs, in proportion to what it is:

- a batch pipeline;
- one operator;
- 5–50 new prospects a week;
- a person in the loop.

Uptime matters less than correctness, cost and not losing work. Each objective says how it is measured *today*, with no new tooling, and what stops it being measured.

## Objectives

| # | What (SLI) | Objective (SLO) | Window | How to measure today | Blocked by |
|---|---|---|---|---|---|
| 1 | **Cost per prospect**: spend per lead that reached `copy_ready` or later | ≤ $0.50 average, and no lead over $0.75 | Rolling 30 days | `outbound report cost --days 30` (per prospect); `provider_calls` grouped by `company_id` | Model spend recorded at $0 without `LLM_PRICES` ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)) |
| 2 | **Copy quality**: sent first emails with no edits | ≥ 80 % (8 of 10, the Phase 2 gate) | Rolling 30 days, at least 10 sent | `outbound report quality` (unedited share) | The Sent sync runs only from `tick` ([R-02](../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7)) |
| 3 | **Pipeline success**: leads that leave each stage as advanced or held, rather than failed | ≥ 95 % per stage | Per run, and rolling 7 days | `run_finished.outcomes`; `runs.counts` | — |
| 4 | **Time to a draft for review**: a manual lead from `new` to `copy_ready` | ≤ 1 business day | Per lead | Events: `created` to `status_changed` → `copy_ready` | Leads waiting on vendors (catch-all) are excluded |
| 5 | **Approved to drafted** | ≤ 1 hour after approval | Per message | Events: message `approved` to `drafted` | Drafting happens only on the next run's deliver stage (B7) |
| 6 | **Safety**: emails drafted that break the safety model | **0** | Always | `tests/` in CI; spot checks of `approved_with_skips` | This is an invariant, not a target |
| 7 | **Erasure** of a person on request | Done within 7 days of the request (the law allows one month) | Per request | The `forgotten` event's time against the request's time (recorded by the operator) | — |
| 8 | **Availability** of the web app during working hours | ≥ 99 % per month (about 7 hours of downtime allowed) | Calendar month | Not measured: no external probe | No probe; `/api/health` is shallow ([R-06](../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database)) |
| 9 | **Run completion**: queued runs that finish (not stuck) | 100 % within 1 hour | Per run | Runs screen; `runs` with `status='running'` and `started_at` older than 1 h | No stale-run recovery ([R-05](../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3)) |

## Error budgets and what to do when they burn

| Objective breached | Response |
|---|---|
| 1 Cost | Stop discovery runs; check `provider_calls` by provider; lower `MONTHLY_CAPS_MICRO_USD` or the ceiling; review the chain ([budget exceeded](runbooks/budget-exceeded.md)) |
| 2 Quality | Review the edits (Review screen, `edit_distance`); improve the sender profile and research questions; consider a better model for copy (Phase 3b D4) |
| 3 Success | Read `stage_failed` for the stage; check vendor health ([vendor 429 or outage](runbooks/vendor-429-or-outage.md)) |
| 6 Safety | A **SEV-1** incident ([incident response](incident-response.md)): stop the worker, suppress, find the cause before anything else is drafted |
| 7 Erasure | Treat as SEV-2: the legal deadline is close |
| 8, 9 Availability, runs | [Runbooks](runbooks/README.md) for the symptom |

## Queries

```sql
-- 1: spend per prospect, last 30 days (with LLM_PRICES set)
SELECT company_id, sum(cost_micro_usd)/1e6 AS usd FROM provider_calls
WHERE workspace_id = :ws AND created_at > now() - interval '30 days' AND company_id IS NOT NULL
GROUP BY company_id ORDER BY usd DESC;

-- 9: runs stuck in running
SELECT id, kind, started_at FROM runs
WHERE workspace_id = :ws AND status = 'running' AND started_at < now() - interval '1 hour';
```

## Planned

Phase 5 (automatic sending) needs real availability and delivery SLOs: a send window, bounce rate under the breaker thresholds, and complaint rate. See [phase-5-automated-sending.md](../../phases/phase-5-automated-sending.md).
