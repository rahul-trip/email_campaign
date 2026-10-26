---
type: reference
status: accepted
date: 2026-10-21
deciders: "@rahul-trip"
introduced_in: 87b4e38
---

# 0019. A country-rule block found by a guard holds the lead; only suppression ends it

## Context

Before this change, a guard that found a blocking country moved the lead to `suppressed`, which is final. Once the operator could switch country rules off or skip them per lead, a rule could come back into force (a skip revoked, the switch turned back on), and the old behaviour would have ended leads for good because of a setting.

## Decision

The runner's guard turns any non-ALLOW country decision, including BLOCK, into a **hold** (`needs_operator` for a block). Only the suppression list moves a lead to `suppressed`. The gate itself still disqualifies a blocked lead on first decision (the operator can requalify it or skip the rule from the gate).

## Consequences

- **Good:** settings are reversible without losing leads; `suppressed` keeps one meaning, do not contact.
- **Bad:** a lead in a blocked country can sit in `held` until the operator acts; the gate and the guards treat BLOCK differently (disqualify vs hold), which must be explained ([safety model](../hld/safety-model.md)).
- **Follow-ups:** none.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep suppressing on a block | A temporary setting would permanently end leads |
| Defer silently | The lead loops invisibly (Phase 3b B1) |

## Evidence in the code

- `outbound/runner/guards.py::Guards.check` (comment explains the rule); `tests/db/test_policy_skip.py`; `tests/db/test_runner.py::test_a_country_that_forbids_cold_email_stops_a_lead_before_a_later_stage`.
