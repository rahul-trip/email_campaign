---
type: reference
status: accepted
date: 2026-10-23
deciders: "@rahul-trip"
introduced_in: 5ca5370, 5d9372f (migrations 0007-0008)
---

# 0025. Composite tenant-bound foreign keys, and one worker scheduling every workspace

## Context

Before Phase 6a there was one workspace and foreign keys pointed `child.parent_id -> parent.id`, which carries no tenant information at all. With many workspaces, that leaves a gap row-level security alone cannot close: Postgres checks a foreign key's referential integrity with the same privilege as the write itself, bypassing RLS — so even a correctly-RLS-scoped connection could insert a child row that names a *parent id from a different workspace*, if nothing else stopped it. Separately, the single-workspace `outbound tick` cron needs to become a scheduler that fairly serves many workspaces without starving any one of them, and must survive a crash mid-run without leaving it stuck `running` forever.

## Decision

Every tenant child table's foreign key is rewritten to `(workspace_id, child_fk) -> (parent.workspace_id, parent.id)` (the `_tenant_fk` helper), with a `UNIQUE (workspace_id, id)` added to the referenced parent. The migration pre-checks for any existing cross-workspace reference and halts rather than reinterpret data; on Postgres each constraint is added `NOT VALID` then validated, to keep the lock window short. Separately, `outbound/worker.py` is rewritten around a `Worker` that `plan()`s work using least-recently-served fairness across active workspaces (checking the platform kill-switch per workspace), runs each workspace's tick on a timer (`--tick-minutes`, default 15) via a `ThreadPoolExecutor`, and `recover_stale()`s any run whose heartbeat has not updated in 30 minutes — replacing the old cron-triggered, single-workspace `outbound tick`.

## Consequences

- **Good:** a cross-workspace reference is refused by the database itself, independent of and in addition to row-level security ([0024](0024-row-level-security-and-least-privilege-roles.md)) — even an owner connection that bypasses RLS entirely still cannot write it. A stuck run from a crashed or redeployed worker self-heals on the next tick cycle rather than staying `running` forever (closing a gap noted before 6a).
- **Bad:** every existing single-column foreign key needed a migration pass; a future tenant table must remember to use `_tenant_fk`, not a plain `ForeignKey`, or it silently loses this protection (code review must catch this, since nothing automated enforces it on a *new* table beyond the RLS isolation test's own table list).
- **Follow-ups:** `PLATFORM_DATABASE_URL` falling back to `DATABASE_URL` when unset is fine for SQLite/single-role rehearsal, but a misconfigured production deployment would run the scheduler as `outbound_app`, which would simply fail to find any workspace due rather than leak data — tracked as a sharper-check item.

## Alternatives considered

| Option | Why not |
|---|---|
| Rely on RLS alone for tenant isolation | FK checks bypass RLS; a cross-tenant reference could still be written even with RLS correctly configured |
| Keep the cron-based single-tick model, parameterised by workspace | Starves workspaces unevenly under any real cron interval, and still has no stale-run recovery or graceful fairness across many workspaces |

## Evidence in the code

- `outbound/db/migrations/versions/0007_tenant_bound_foreign_keys.py`, `0008_workspace_slug_and_status.py`; `outbound/db/models.py::_tenant_fk`.
- `outbound/worker.py` (`Task`, `Job`, `Worker.plan`, `recover_stale`, `run_forever`).
- `tests/db/test_rls.py`, `tests/db/test_scheduler.py`.
