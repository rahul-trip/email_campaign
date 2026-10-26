---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §4](../../PLAN.md#4-research-recommendations-verdicts) verdict 17 (simplified); c3d3228 (#1)
---

# 0011. Operator input wins: the engine never overwrites a field the operator set

## Context

The operator often knows better than research (the right country, the company's real name, a person's title). Research runs again on retries and reruns, and must not silently undo a correction. A full "manual / discovered / effective" column triple for every field would triple the schema.

## Decision

Rows that both the operator and the engine write carry `manual_fields`, the list of fields the operator set. An engine write to one of those fields is not applied; it is recorded as a `field_changed` event with `applied: false`, so the engine's opinion is kept without replacing the operator's. Facts that can have several values (addresses, notes, consents) are child rows instead.

## Consequences

- **Good:** corrections stick; the engine's alternative is still visible in the timeline; no extra columns.
- **Bad:** an operator value is never refreshed by the engine, even when the engine is right, until the operator clears it.
- **Follow-ups:** binding rule 7 in [CLAUDE.md](../../../CLAUDE.md).

## Alternatives considered

| Option | Why not |
|---|---|
| Manual, discovered and effective columns for every field | Triples the schema for little gain |
| Last writer wins | Research reruns would undo the operator's corrections |

## Evidence in the code

- `outbound/db/repositories/base.py::ScopedRepository._apply_changes`.
- `tests/db/test_companies_repo.py::test_the_engine_cannot_overwrite_an_operator_value_but_the_attempt_is_recorded`, `tests/db/test_people_repo.py::test_the_engine_cannot_overwrite_an_operator_given_contact_field`.
