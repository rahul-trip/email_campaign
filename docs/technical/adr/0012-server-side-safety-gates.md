---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §11](../../PLAN.md#11-compliance-and-deliverability); c3d3228 (#1)
---

# 0012. Safety gates are server-side and checked again before every draft or send

## Context

A lead can wait days between qualification and drafting. Meanwhile a suppression can be added, a country rule edited, a consent withdrawn or an address bounce. A check made once, early, would let a stale "yes" through. A check made only in the user interface could be bypassed through the API.

## Decision

Suppression, the country policy and the safe-to-send rule are pure functions in `outbound/domain/policies.py`, applied by server code only. They are checked at the gate, by the runner's guard before every later stage, by the stages that choose a recipient, at approval, and once more by deliver (`check_send`) immediately before a draft is saved. A failing late check holds the lead and withdraws its approved email.

## Consequences

- **Good:** the latest state always wins; no client can skip a check; rules are unit-tested without a database.
- **Bad:** the same rule runs several times per lead (cheap: no paid calls); late holds can surprise the operator after approval (the reason is shown).
- **Follow-ups:** binding rule 8 in [CLAUDE.md](../../../CLAUDE.md); the [safety model](../hld/safety-model.md).

## Alternatives considered

| Option | Why not |
|---|---|
| Check once at the gate | Stale decisions reach the mailbox |
| Check in the UI before calling the API | Bypassable; duplicated logic |

## Evidence in the code

- `outbound/domain/policies.py` (`decide_country_policy`, `check_send`); `outbound/runner/guards.py::Guards.check`; `outbound/stages/deliver.py`.
- `tests/db/test_review_and_deliver.py::test_a_suppression_added_after_approval_stops_the_draft`.
