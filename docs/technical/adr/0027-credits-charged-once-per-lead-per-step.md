---
type: reference
status: accepted
date: 2026-10-24
deciders: "@rahul-trip"
introduced_in: cca1800, 67236fd
---

# 0027. A plan's credit for a step is charged once per lead, except rewrites, which charge every time

## Context

With paying customers on different plans, the platform needs a usage ceiling independent of (and in addition to) the dollar-cost budget guard ([0005](0005-metered-decorator-and-ledger.md)) — a free-tier customer should not be able to run the same lead through research ten times and consume ten units of plan credit, but a customer legitimately asking the copy stage to "write it again" five times for one lead is doing five genuinely different pieces of work. The two cases need different rules, and the rule needs to be enforced somewhere a retried or reset lead cannot quietly bypass it.

## Decision

Define `UsageStep` as seven steps, each mapping to a status transition a lead makes once (`DISCOVERY`, `MANUAL`, `RESEARCH`, `EMAIL`, `COPY`, `DELIVER`) plus one the person can repeat (`REWRITE`, the copy stage's "write it again"/"ask for changes" action). `ONCE_PER_LEAD = frozenset(UsageStep) - {REWRITE}`, enforced not just in application logic but as a partial unique index on `usage_events (workspace_id, step, company_id) WHERE step <> 'rewrite'` — the database refuses a second charge for the same step on the same lead, so even a bug in the service layer cannot double-charge or let a reset-and-rerun lead be charged twice. `usage_events` carries no foreign key to `companies`, so deleting a lead never refunds its credit retroactively, which a cascading delete could otherwise do by accident.

## Consequences

- **Good:** the once-per-lead rule is a database constraint, not a check that a future code path could forget. `REWRITE`'s unlimited-repeat semantics are expressed structurally (simply excluded from the unique index) rather than as a special case scattered through the charging code.
- **Bad:** a lead legitimately reset and re-researched after a data-fix or an operator's deliberate "start over" is **not** re-charged for `RESEARCH` (the once-per-lead row already exists) — correct for the customer, but means "credits used" is not strictly "distinct pieces of paid work this month" when resets happen; the discrepancy is visible in the ledger, not hidden.
- **Follow-ups:** entitlement credit limits (count-based) and the metering budget guard (cost-based, [0005](0005-metered-decorator-and-ledger.md)) are independent guards that can each block a step for different reasons; a support conversation needs to check both when a customer asks "why can't I run this lead."

## Alternatives considered

| Option | Why not |
|---|---|
| Charge every stage execution, regardless of repeats | Penalises retries after transient failures and resets, which are not the customer's fault or request |
| Enforce once-per-lead only in the service layer, no database constraint | A concurrent double-attempt, or a future bug, could double-charge with nothing to catch it |

## Evidence in the code

- `outbound/domain/entitlements.py` (`UsageStep` via `outbound/domain/enums.py`, `ONCE_PER_LEAD`, `available`, `compute_quota`).
- `outbound/db/models.py::UsageEventRow` (the partial unique index).
- `tests/domain/test_entitlements.py`, `tests/services/test_entitlements.py`.
