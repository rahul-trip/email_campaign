---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §5](../../PLAN.md#5-architecture) ("Deliberately not used"); c3d3228 (#1)
---

# 0002. The companies table is the work queue; the runs table queues runs

## Context

Each lead moves through a fixed sequence of stages, often waiting hours or days (for a catch-all answer, a consent, an operator). Work must survive crashes and deploys, and a rerun must never pay twice. The web app must not run the pipeline inside an HTTP request. Volume is tiny: tens of leads a week.

## Decision

There is no message broker. A lead's `status` names the stage that wants it, and `next_action_at` says when it is due. The runner selects due leads per stage (`CompanyRepository.due`), indexed by `ix_companies_queue`. Runs requested from the API are rows in `runs` with status `queued`; the worker claims the oldest with `SELECT … FOR UPDATE SKIP LOCKED` and polls every 2 seconds when idle. Periodic work (retries, the catch-all poll, the Sent sync) runs in `outbound tick`, started by a scheduler.

## Consequences

- **Good:** no extra infrastructure; the queue is transactional with the data it describes; a crash loses nothing because status only changes in the per-lead write; the state is visible with a SQL query.
- **Bad:** polling, not push (up to 2 s latency for a queued run); `SKIP LOCKED` does nothing on SQLite, so only one worker is safe there; periodic work needs an external scheduler, which production does not have yet ([R-02](../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7)); runs have no lock against each other ([R-05](../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3)).
- **Follow-ups:** schedule `tick` in production (Phase 3b B7); one run per workspace at a time and stale-run recovery (B2, B3).

## Alternatives considered

| Option | Why not |
|---|---|
| Celery or RQ with Redis | A second stateful service to run and back up, and a queue that can disagree with the database |
| Postgres LISTEN/NOTIFY | Not available on SQLite in development; polling is adequate at this volume |
| A jobs table | Status plus `next_action_at` already expresses every schedule the engine needs (SCHEMA.md, "Not in v1") |
| A managed queue (Cloud Tasks, SQS) | Vendor lock-in and cost for a few runs a day |

## Evidence in the code

- `outbound/db/repositories/companies.py::CompanyRepository.due`; index `ix_companies_queue` in `outbound/db/models.py`.
- `outbound/db/repositories/audit.py::RunRepository.claim_next`; `outbound/worker.py::Worker.run_forever`.
- `outbound/runner/tick.py::Tick`.
