---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Capacity and limits

The limits that apply to Outbound, and which gives way first. The design target is **5–50 new prospects a week**. At that volume the only limit near its edge is the database connection pool.

## Database connections

| Process | Pool | Notes |
|---|---|---|
| `api` | up to `DATABASE_POOL_SIZE` (5) | Pre-pinged, recycled every 300 s, no overflow |
| `worker` | up to 5 | |
| `migrate` (during a deploy) | up to 5 for `seed`; Alembic itself uses no pool | Exits when done |
| Each `oc run … outbound <cmd>` | up to 5 | One-off containers |
| **Supabase small-plan session pooler** | **about 15 clients in all** | |

`api` + `worker` + `migrate` = 15. That is the whole limit before any one-off command ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)).

Each process holds few connections in practice: transactions are milliseconds long, and the worker is single-threaded. So `DATABASE_POOL_SIZE=2` or `3` is a safe setting on a small plan. Set it in Doppler and restart. Symptom of exhaustion: `max clients reached` ([runbook](runbooks/db-max-clients.md)).

## Throughput

| Path | Limit |
|---|---|
| Pipeline | One worker, one lead at a time. Research and copy take seconds to tens of seconds per lead (model calls up to 90 s each), so a run of 50 new leads takes minutes to an hour. Fine at the design volume |
| Leads per run | `limit` per stage (default 50, at most 500 from the API) |
| Discovery | `discover` 1–50 companies per run |
| API | One uvicorn process; the handlers are synchronous (a thread pool). Enough for one operator |
| Intake | One search per name-only row, before the batch is written |

Running two pipelines in parallel is not supported. There is no run lock ([R-05](../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3)), and on SQLite the claim is not exclusive.

## Vendor limits

| Vendor | Limit | Handling |
|---|---|---|
| Tavily | Plan and pay-as-you-go limits (432, 433 answers); rate limits per plan | `BudgetExceeded`; 429 retried with `Retry-After` |
| Companies House | 600 requests per 5 minutes | 429 retried |
| Scrubby | 10 requests a second (documented) | — |
| MyEmailVerifier | 100 free requests a day, then paid | Recorded at the paid price |
| Others | Per plan; not documented here | 429 retried; check the vendor dashboard |
| LLM | Provider rate and token limits; `LLM_MAX_TOKENS` 4,000 per reply | 429 retried; a cut-off reply is an error |

## Spend limits

| Control | Where | Default |
|---|---|---|
| Per-prospect ceiling | Workspace setting `budget_per_prospect_micro_usd` | $0.50 |
| Monthly cap per provider | `MONTHLY_CAPS_MICRO_USD` | none |
| Vendor-side caps | Each vendor's account | Set them too: they are the last line if the app's accounting is wrong ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5), [R-04](../tech-debt-and-risks.md#r-04--p1--cost-the-budget-cap-prices-a-catch-all-submit-at-0)) |

## Request and data limits

| Limit | Value |
|---|---|
| Webhook body; targets per call | 1 MB; 1–200 |
| Upload | 2 MB |
| Strings in API requests | 10,000 characters unless lower |
| Sent sync per pass | 500 drafted messages; 500 sent messages read |
| Catch-all poller per pass | 50 leads |
| Contacts tried per lead | 3 |
| Copy rewrites | 2 |
| Research pages | 5 URLs, 6,000 characters each, 18,000 in total |

## Containers and the VM

| Container | Memory limit | Restart |
|---|---|---|
| `migrate` | 512 MB | no |
| `api` | 1 GB | unless-stopped |
| `worker` | 1 GB | unless-stopped |

There are no CPU or pids limits. The VM is shared with another application and builds the image on deploy (Node and Python stages); a build can slow the other app briefly. Disk use grows with up to 7 release folders and their images, plus Docker logs (10 MB × 5 per container).

## How it scales, if it must

In order of need:

1. A smaller pool per process.
2. A deep health check.
3. A run lock (B2), then more than one worker on Postgres.
4. A larger Supabase plan.
5. Moving off the shared VM.

Nothing in the design needs a queue broker below thousands of leads a week ([ADR 0002](../adr/0002-the-table-is-the-queue.md)).

## How to refresh this page

```bash
grep -n "mem_limit\|restart" deploy/compose.yml
grep -n "pool_size\|max_overflow\|pool_recycle" outbound/db/session.py
grep -rn "MAX_\|_LIMIT\|limit=" outbound/stages outbound/services/webhook.py outbound/api/routers/*.py | head -30
```
