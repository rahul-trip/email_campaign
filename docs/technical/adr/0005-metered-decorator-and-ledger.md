---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §5](../../PLAN.md#5-architecture) (patterns, hard contract 2); c3d3228 (#1)
---

# 0005. Every paid call goes through a Metered decorator that commits its own ledger row

## Context

The budget is $0.50 per prospect. Vendors charge per call, some even for a cache-worthy repeat. Spend must be capped before a call, attributed to a run, company and contact after it, and recorded even if the stage then fails. Stages should not each re-implement this.

## Decision

Each port has a `Metered*` wrapper around a shared `Meter`. `Meter.call` does, in order: a cache lookup by request hash (served as a `cache_hit` row at cost 0), a budget check (monthly cap per provider; per-prospect ceiling), the call, then a `provider_calls` row with outcome, cost and latency, **committed in its own unit of work**. Stages receive only metered providers from `outbound/pipeline.py::assemble`; they never construct a vendor client.

## Consequences

- **Good:** one place for caching, caps and cost; spend is recorded even when the lead's write fails; reruns are cheap; reports come straight from the ledger.
- **Bad:** every paid path must be wrapped (a test checks the known paths); prices must be configured or calls record $0 ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)); the pre-call price lookup must use the same key as the charge ([R-04](../tech-debt-and-risks.md#r-04--p1--cost-the-budget-cap-prices-a-catch-all-submit-at-0)).
- **Follow-ups:** binding rule 3 in [CLAUDE.md](../../../CLAUDE.md); the [metering LLD](../lld/metering.md).

## Alternatives considered

| Option | Why not |
|---|---|
| Each stage caches and counts its own calls | Duplicated logic; a forgotten path spends without a cap |
| Record spend in the stage's own transaction | A failed stage would lose the record of money already spent |
| Rely on vendor dashboards for spend | No per-lead attribution, no cap before the call |

## Evidence in the code

- `outbound/metering/metered.py` (`Meter`, `MeteredFinder`, `MeteredVerifier`, `MeteredResolver`, `MeteredSearch`, `MeteredLlm`, `MeteredRegistry`, `call_scope`); `outbound/metering/budget.py`.
- `tests/db/test_metered.py`, `tests/db/test_robustness.py::test_a_meter_applies_the_monthly_cap_to_every_path`.
