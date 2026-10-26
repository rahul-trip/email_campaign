---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §5](../../PLAN.md#5-architecture) (hard contract 1); c3d3228 (#1)
---

# 0006. No database transaction across a network call; one short write per lead with optimistic locking

## Context

Stages call vendors and models that take seconds. Holding a transaction (and its locks) across those calls would block the operator's edits, exhaust the connection pool, and make a crash leave half-written state. The operator may edit a lead while a stage works on it, and their edit must win.

## Decision

A stage reads what it needs in short read-only transactions (`ctx.read`), does its network work with no transaction open, and returns a `StageResult`. The runner then writes everything in one short transaction: engine fields, child rows, and the status transition, each checking `row_version`. A version conflict drops the stage's result (and runs its `undo` for any outside effect).

## Consequences

- **Good:** transactions last milliseconds; an operator edit always wins; a crash leaves either the old state or the new one, never a mix.
- **Bad:** a stage may do work whose result is then discarded (and must provide `undo` for outside effects such as a saved draft); only `companies` and `messages` carry `row_version` ([R-15](../tech-debt-and-risks.md#r-15--p2--correctness-runs-and-three-tables-bypass-the-usual-guards)).
- **Follow-ups:** binding rule 5 in [CLAUDE.md](../../../CLAUDE.md).

## Alternatives considered

| Option | Why not |
|---|---|
| One transaction per lead around the whole stage | Locks and connections held for seconds; pool exhaustion on Supabase |
| Pessimistic row locks (`SELECT … FOR UPDATE`) on the lead | Blocks the operator's edits for the length of a model call |

## Evidence in the code

- `outbound/stages/base.py` (`Reader`, `StageContext`, `StageResult`); `outbound/runner/runner.py::Runner._process`, `Runner._apply`.
- `tests/db/test_runner.py::test_an_operator_edit_during_the_stage_wins_and_the_lead_is_tried_again`, `…::test_a_saved_draft_is_taken_back_when_the_database_write_cannot_happen`.
