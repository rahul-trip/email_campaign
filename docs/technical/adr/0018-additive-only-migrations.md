---
type: reference
status: accepted
date: 2026-10-19
deciders: "@rahul-trip"
introduced_in: 133fd06 (#11), stated in DEPLOY.md §1.2 and `deploy/remote-deploy.sh`
---

# 0018. Migrations are additive, so the previous release can run on the newer schema

## Context

Deploys run `migrate` before starting the new `api` and `worker`, and a failed deploy rolls back to the previous release. A rollback cannot safely run a downgrade (it can drop data), so the old code must be able to run against the schema the new release left behind.

## Decision

Every migration is **additive** (expand/contract): add tables, nullable or defaulted columns, and widened `CHECK` lists; never drop or rename in the same release that stops using something. Removing a column or value is a later, separate release, after no deployed code uses it. A rollback never runs `db downgrade`.

## Consequences

- **Good:** a rollback needs no data migration; old and new code can briefly coexist.
- **Bad:** **the current rollback mechanism does not honour this decision**: it restarts the previous release's `migrate`, whose `db upgrade` fails on an unknown newer revision, so `api` and `worker` never start ([R-01](../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down)). The schema would be compatible; the step that checks it is not. Contract steps also need two releases.
- **Follow-ups:** fix the rollback (start only `api` and `worker`, or make `migrate` accept a database ahead of the code); the [migrations policy](../data/migrations.md) states the rule.

## Alternatives considered

| Option | Why not |
|---|---|
| Downgrade on rollback | Downgrades can drop data (`outbound db downgrade` warns so); 0003's downgrade refuses while unconfirmed rows exist |
| Roll forward only | Still needed as a fallback, but a quick return to a known-good release is valuable |

## Evidence in the code

- `outbound/db/migrations/versions/0002…0005` (all additive); `deploy/remote-deploy.sh::rollback` (comment: "Migrations are not undone").
