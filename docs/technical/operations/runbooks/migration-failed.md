---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# A migration failed during a deploy

| | |
|---|---|
| **Severity** | SEV-2 |
| **Impact** | The deploy rolls back; the database may be at the old revision (the migration did not run) or partly changed (Postgres runs DDL in a transaction, so usually not). |
| **Signals** | `migrate` exited non-zero with an Alembic or database error (not `Can't locate revision`, which is [R-01](deploy-failed-or-rollback.md)) |
| **Related** | [migrations](../../data/migrations.md), [deploy failed or rollback](deploy-failed-or-rollback.md) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --tail 100 migrate
oc run --rm --no-deps api outbound db current      # which revision is the database at?
```
Compare with the latest revision in the failed release (`releases/<sha>/outbound/db/migrations/versions/`).

## 2. Contain

The automatic rollback starts the previous release. If the database is still at the old revision, that works.

## 3. Fix

- **The database is at the old revision:** fix the migration in a new commit and test it up and down on both databases (`uv run --with pgserver python -m scripts.pg_tests tests/db -q`), then deploy.
- **The database is partly changed** (rare; SQLite batch mode or a non-transactional step): restore from backup, or repair by hand with care, then deploy the fix.

## 4. Verify

`outbound db current` shows the new head; `migrate` exits 0; the post-deploy checks pass.

## 5. Follow up

Add the case to the migration's tests.
