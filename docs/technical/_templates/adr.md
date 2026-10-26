---
type: reference
status: proposed            # proposed | accepted | superseded by NNNN | deprecated
date: YYYY-MM-DD            # when the decision was made (from git history for backfilled records)
deciders: "@rahul-trip"
introduced_in: <commit SHA or PR link>
---

# NNNN. <Short decision, stated as a choice: "The companies table is the work queue">

## Context

What forces are at play: the requirement, the constraint, the cost or the risk that made a decision necessary. Facts only, with links to code or documents.

## Decision

What was decided, in one or two sentences, in the active voice ("We use …").

## Consequences

- **Good:** what this makes easier or safer.
- **Bad:** what this costs or rules out. Name the trade-off honestly.
- **Follow-ups:** what this obliges us to do, with links (rules in CLAUDE.md, tests, register entries).

## Alternatives considered

| Option | Why not |
|---|---|
| … | … |

## Evidence in the code

Where the decision is enforced or visible, as `path::symbol` references (an import-linter contract, a test, a CHECK constraint).

<!--
Rules for ADRs:
- Write one for a decision that changes structure, quality attributes, dependencies, interfaces or how
  the system is built. Product and compliance policy goes in PLAN.md instead.
- Once accepted, an ADR is never edited except for its status line. To change the decision, write a new
  ADR that supersedes it, and set this one's status to "superseded by NNNN".
- Number in order; never reuse a number. Add the record to adr/README.md.
-->
