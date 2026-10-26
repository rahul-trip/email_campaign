---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §5](../../PLAN.md#5-architecture), §7; c3d3228 (#1)
---

# 0007. Status changes only through transition tables, each writing an event

## Context

Leads, messages, addresses and contacts have lifecycles with legal consequences (an approved email must not become a draft after an opt-out). Every change must be explainable later: who moved what, from where, and why.

## Decision

Each lifecycle is a transition table in `outbound/domain/state_machines.py`. Repositories call `check(current, target)` before every status change and append a `status_changed` event in the same session, with the actor and reason. A move that is not in the table raises `IllegalTransition`. Status values are `StrEnum`s mirrored by `CHECK` constraints.

## Consequences

- **Good:** illegal moves are impossible rather than unlikely; the event log is a complete audit trail; adding a status forces a decision about its exits (the table refuses to build otherwise).
- **Bad:** the event table grows without bound (no retention yet); runs do not follow this rule today ([R-15](../tech-debt-and-risks.md#r-15--p2--correctness-runs-and-three-tables-bypass-the-usual-guards)).
- **Follow-ups:** binding rule 4 in [CLAUDE.md](../../../CLAUDE.md); the [state machines](../hld/state-machines.md) reference.

## Alternatives considered

| Option | Why not |
|---|---|
| Status as a free column, checked by callers | Every caller must remember every rule |
| A workflow engine | Heavy for five small tables of transitions |
| Event sourcing | The current state is what the runner queries; events are an audit log, not the source of truth |

## Evidence in the code

- `outbound/domain/state_machines.py` (`StateMachine`, `COMPANY`, `MESSAGE`, `EMAIL`, `CONTACT`, `RUN`).
- `outbound/db/repositories/companies.py::CompanyRepository.transition`; `outbound/db/repositories/base.py::EventRepository`.
- `tests/domain/test_state_machines.py`.
