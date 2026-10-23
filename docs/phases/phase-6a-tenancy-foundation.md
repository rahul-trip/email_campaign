# Phase 6a — Tenancy foundation

**Goal:** one deployment serves many workspaces, and the database itself keeps them apart.
- The API builds its services per request.
- The worker serves every workspace fairly.
- Row-level security holds even if application code forgets a filter.

**Depends on:** Phase 3b, including B2, B3, B4, B5 and B7 (migration 0006; see [phase-3b-hardening.md](phase-3b-hardening.md), §8).

**Status (2026-10-23): code complete** on branch `phase-6/tenancy-foundation`.
- **Tests:** 1,601 pass on Postgres connected as `outbound_app`/`outbound_platform`, and 1,593 on SQLite.
- **What the gate still waits on:** creating the roles in Supabase, then rehearsing on a production copy and deploying (see "Closing the phase").
- **Prerequisites done here:** B2, B3, B4 and B7 were built in this phase; B5 (model prices) is still open.

**Built differently from the text below** (each for a reason found while building):
- **No `FORCE ROW LEVEL SECURITY`.** The owner still runs migrations and `seed`, which FORCE would block. The startup self-check refuses to run as the owner instead.
- **Ticks are not queued runs.** The worker runs each workspace's tick directly on a timer. A tick skips the pipeline when no lead is due, so a quiet workspace does not fill its Runs screen with empty runs.
- **The owner's connection:** a `POSTGRES_MIGRATE_URL` setting serves single-config setups such as the local rehearsal. Production can use a separate Doppler config through the optional `DOPPLER_MIGRATE_TOKEN` secret.
- **The import-linter contract** forbids `outbound.db.platform` to stages, the runner, metering and all services except `services.seed`, which creates workspaces.
- **`actor` as a service constructor argument** moves to 6b, where real users first exist.
- **The repository-walk test** for workspace predicates is replaced by stronger proof: the whole Postgres suite runs as `outbound_app`, so any unscoped query returns nothing and fails its test. `tests/db/test_rls.py` checks the same with raw, unfiltered SQL.

**Gate:**
- **The Phase 6 isolation test:** with application-level scoping patched out, no query made for workspace A returns a row of workspace B.
- **The whole Postgres suite** passes while connected as `outbound_app`.
- **Production** runs as `outbound_app`, and the startup self-check passes there.
- **Migrations 0007–0009** have been rehearsed on a restored copy of production before running for real.
- **Two seeded workspaces** run the full pipeline at the same time in one worker, with no `provider_calls` row attributed to the wrong workspace.

## Scope

**In:**
- closing the known scoping gaps;
- composite foreign keys;
- workspace slug and status;
- the platform unit of work;
- row-level security and database roles;
- services built per request;
- the multi-tenant worker;
- the deploy changes.

**Out:**
- users and sign-in (6b);
- mailbox connection (6c);
- plans and limits (6d).

Until 6b, the API still resolves the one configured workspace and keeps today's operator login.

## Tasks

### 6a.1 Close the scoping gaps

- [ ] Joins that filter only the driving table also filter the joined table by workspace:
  - `db/repositories/contacts.py:193-203`;
  - `messages.py:123-137`;
  - `imports.py:127-143`.
- [ ] Deletes by id carry the workspace: `db/repositories/erasure.py:176-180` and `234-235`.
- [ ] **The runner** reads the workspace through `uow.workspace()`, inside the unit of work it already holds (`runner/runner.py:181-192`), not through `AdminUnitOfWork`.
- [ ] **`pipeline._workspace`** goes, along with the `AdminUnitOfWork` read in `build_meter` (`pipeline.py:122-142`). The budget is read live (3b B4).
- [ ] **`SettingsService`** (`services/settings.py:73-121`) reads and writes its own workspace through scoped methods. Each change and its event are committed together; today they are two transactions.
- [ ] **Lookups across workspaces** move to `PlatformUnitOfWork` (6a.4): `Container.workspace_id` (`bootstrap.py:25-42`), `services/seed.py:23` and the scripts.
- [ ] Then delete `UnitOfWorkFactory.admin()` and `AdminUnitOfWork` (`db/uow.py:103-140`).

**Done when:** every existing cross-workspace test passes, and a test that walks every repository method finds no query without a workspace predicate.

### 6a.2 Composite foreign keys (migration 0007)

- [ ] A pre-check counts cross-workspace references for every foreign key. The migration stops and names the rows if any exist.
- [ ] Add `UNIQUE (workspace_id, id)` on every parent table.
- [ ] Each child foreign key becomes `(workspace_id, parent_id) → parent (workspace_id, id)`, with an explicit name.
- [ ] **Postgres:** each constraint is added `NOT VALID`, then `VALIDATE CONSTRAINT`, so the lock is short.
- [ ] **SQLite:** Alembic batch mode. `db/migrations/env.py` keeps `foreign_keys` off during the table rebuild.
- [ ] `tests/db/test_runner.py:567-590` shows the database accepts a cross-workspace reference today. It becomes a test that the database **refuses** one (`IntegrityError`).

**Done when:** the migration runs up and down on both databases against a populated copy, and the refusal test passes.

### 6a.3 Workspace slug and status (migration 0008)

- [ ] `workspaces.slug`: unique, URL-safe, generated from the name.
- [ ] Drop `UNIQUE (name)` (migration 0002), because two customers may share a name.
- [ ] `workspaces.status`: `active`, `paused` (engine stopped by an admin), `suspended`, `pending_deletion`, `deleted`.
  - It is a new `WorkspaceStatus` enum with a `CHECK`.
  - Transitions live in `domain/state_machines.py`, and each one writes an event.
- [ ] `workspaces.deletion_due_at`.
- [ ] `Container.workspace_id` and the CLI's `--workspace` accept a slug.

**Done when:** the enum-versus-`CHECK` test passes, there is a transition test per edge, and the CLI resolves slugs.

### 6a.4 Platform unit of work

- [ ] `outbound/db/platform.py`: `PlatformUnitOfWork`, on the platform engine (6a.5). It reads across workspaces:
  - the workspace directory (by slug; list);
  - workspaces with due work (ids only);
  - stale runs;
  - aggregates for the admin console (6d).

  It writes platform tables only. Tenant writes, including run claims, always go through a tenant unit of work.
- [ ] **import-linter:** a forbidden contract stops `outbound.stages`, `outbound.runner` and `outbound.metering` from importing `outbound.db.platform`, and also every service except `services/admin.py` and `services/identity.py`. `bootstrap.py` and `worker.py` may use it.

**Done when:** `uv run lint-imports` passes, and each query has a test.

### 6a.5 Row-level security and database roles (migration 0009, Postgres only)

**Setting the workspace on every transaction:**
- [ ] A SQLAlchemy Session `after_begin` listener in `db/session.py` (in `make_session_factory`) runs `SELECT set_config('app.workspace_id', :ws, true)` from `session.info["workspace_id"]`.
  - `UnitOfWork.__enter__` (`db/uow.py:50`) sets that value.
  - Services commit in the middle of a unit of work, so one `SET` per unit of work is not enough. The `true` keeps the setting inside the transaction, so a pooled connection never carries a tenant into its next use.
  - The Meter's ledger writes open their own unit of work, so they are covered without change.
- [ ] Engine-level code that bypasses the session (`bootstrap.py:31`, the `empty_tables` test fixture) runs as the owner.

**Migration 0009:**
- [ ] Creates the roles `outbound_app` and `outbound_platform` as `NOLOGIN` if they are missing.
- [ ] Grants:
  - `outbound_app`: DML on tenant tables;
  - `outbound_platform`: SELECT on tenant tables, plus writes on platform tables as they arrive in 6b–6g;
  - `ALTER DEFAULT PRIVILEGES` for both;
  - no grant on `alembic_version`.
- [ ] RLS `ENABLE` and `FORCE` on every tenant table, with these policies:
  - `outbound_app`: `USING / WITH CHECK (workspace_id = current_setting('app.workspace_id', true))`;
  - `outbound_platform`: `FOR SELECT USING (true)`;
  - `workspaces`: the row whose `id` is the setting. 6b adds the user's own workspaces through `app.user_id`.
- [ ] Revokes everything from `anon` and `authenticated`. This is the Data API finding, E8 in 3b.

**Connections and startup:**
- [ ] Passwords are set by hand ([../DEPLOY.md](../DEPLOY.md)), never in a migration.
  - Through the shared pooler, the user name is `outbound_app.<project-ref>`.
  - Roles have no `VALID UNTIL`; an expired role fails at the pooler with `EAUTHQUERY`.
- [ ] `bootstrap.py` builds two engines:
  - tenant: `POSTGRES_URL`, connecting as `outbound_app`;
  - platform: `POSTGRES_PLATFORM_URL`, connecting as `outbound_platform`, pool size 2.

  `POSTGRES_MIGRATE_URL` (the owner) is used only by `outbound db upgrade` in the `migrate` container.
- [ ] **Startup self-check** in `serve` and `worker`, on Postgres. Refuse to start if `current_user`:
  - is a superuser;
  - has `rolbypassrls`;
  - owns `companies`;

  or if any tenant table lacks `relrowsecurity` and `relforcerowsecurity`.

**Tests and CI:**
- [ ] The tests run as `outbound_app`.
  - `scripts/pg_tests.py` creates the roles and runs the suite through an app-role engine.
  - The owner engine is used only for setup and cleanup.
- [ ] CI's Postgres version is pinned to Supabase's major version.

**Done when:**
- `tests/db/test_rls.py` passes. It checks that:
  - unscoped selects return only the tenant's own rows;
  - no setting returns no rows;
  - a cross-tenant insert or update is refused;
  - every tenant table has RLS, FORCE and a policy;
  - `anon` and `authenticated` hold no grants.
- The whole suite passes as `outbound_app`.

### 6a.6 Services per request

- [ ] **`ProviderSet`:** raw vendor adapters, built once per process by `real_providers` (`pipeline.py:96-119`). They hold no workspace.
- [ ] **`ServicesFactory.for_tenant(workspace_id, actor)`** replaces the startup singleton (`api/deps.py:21-62`, `api/app.py:130-153`).
  - Per request, it wraps the shared adapters in that workspace's meters. `build_services` (`deps.py:35-57`) is already a plain factory.
  - Routers keep `Depends(services)`. Only `api/deps.py` changes, and it gets a `tenant()` dependency. Until 6b that dependency returns the configured workspace.
- [ ] **`actor`** becomes a constructor argument of the services, replacing the `actor=OPERATOR` defaults. Until 6b it is `operator`.
- [ ] **Remove the per-call rebuilds** in `metered_writer_or_none` and `metered_search_or_none` (`pipeline.py:225-243`). Today each one reads the workspace and creates a new httpx client on every call.
- [ ] **Logs** bind `workspace_id` per request (`api/request_log.py`).

**Done when:** the API tests pass unchanged, and a test shows two requests for two workspaces getting two meters and two ledgers.

### 6a.7 The multi-tenant worker

- [ ] **`worker.py`:** a scheduler loop and a `ThreadPoolExecutor` sized by the setting `WORKER_THREADS` (default 4).
- [ ] **Each cycle:**
  1. The platform unit of work returns the workspaces with queued runs or a due tick, least recently served first (ids only).
  2. For each one, `uow.runs.claim_next()` (`db/repositories/audit.py:44-59`) runs in that workspace's own context.

  3b B2 already ensures at most one running run per workspace.
- [ ] **A pipeline is assembled per claimed run** (`pipeline.assemble`), because `Runner._run_id` (`runner/runner.py:90, 179, 212`) is per-run state. Context variables are cleared when each task starts.
- [ ] **Tick runs** are queued per active workspace every 15 minutes (3b B7) and claimed the same way.
- [ ] **Skipping:**
  - workspaces whose status is not `active`;
  - from 6d, workspaces whose access level is not `full`;
  - everything while the platform kill switch is on (6d).
- [ ] **A per-provider semaphore** in `HttpClient` (`providers/http.py:60`) caps concurrent calls on the shared vendor keys, at 4 per provider by default. Research fans out to four workers, so K threads could otherwise make 4K calls at once.
- [ ] **`outbound worker --workspace` is removed.** One-off CLI commands keep `--workspace`.

**Done when:** a scheduler test with two workspaces and K=2 shows:
- one run per workspace at a time;
- the least recently served workspace first;
- stale runs recovered;
- every ledger row in the right workspace.

### 6a.8 Deploy and documents

- [ ] `deploy/compose.yml`:
  - `migrate` gets its own Doppler config and token, holding the owner URL;
  - `api` and `worker` get the app and platform URLs.
- [ ] [../DEPLOY.md](../DEPLOY.md): the roles and their passwords, the pooler user names, the three URLs, and the Data API staying off.
- [ ] [../SCHEMA.md](../SCHEMA.md) updated for migrations 0007–0009.
- [ ] [../PLAN.md](../PLAN.md) §5: the tenant context and the platform unit of work.
- [ ] [../../CLAUDE.md](../../CLAUDE.md) rule 6.
- [ ] Rehearse 0007–0009 on a restored copy of production (a Supabase backup, or `pg_dump` into a scratch project) before running them for real.

## Tests that must exist

- `tests/db/test_rls.py`: own rows only, no setting returns nothing, cross-tenant writes refused, the catalog check.
- The composite foreign-key refusal test.
- The repository-walk test for workspace predicates.
- The scheduler test (6a.7).
- Services per request (6a.6).
- The startup self-check, against faked catalog answers.
- Migrations 0007–0009 up and down on SQLite and Postgres, on a populated database.

## Closing the phase (what only you can do)

1. Create the two logins in Supabase and set the Doppler URLs ([../DEPLOY.md](../DEPLOY.md), section 1.2a).
2. Restore a production backup into a scratch Supabase project, run `outbound db upgrade` against it, and check that the self-check prints `ok`.
3. Deploy. Confirm the worker logs `service_started` and no `tenant_isolation_unsafe`.
4. Seed a second workspace (`outbound seed --workspace "Test Co"`), queue a run in each, and confirm both run.

## Gate record

- Date:
- Isolation test with scoping bypassed: `tests/db/test_rls.py`, 8 tests, pass on Postgres 16 as `outbound_app` (2026-10-23)
- Postgres suite as `outbound_app`: 1,601 passed, 1 skipped (2026-10-23)
- Rehearsal on a production copy:
- Checked by:
