# Phase 6 — SaaS-ready

**Goal:** more than one workspace can use the same deployment safely, with real users and database-enforced isolation.

**Depends on:** Phase 2. This phase can move ahead of Phase 5 if a second workspace is needed sooner.

**Gate:** a second workspace, seeded with its own leads, runs the full pipeline. Automated tests then confirm:
- no API call, query or export from workspace A returns any row from workspace B;
- the same holds when application-level scoping is deliberately bypassed, because row-level security still blocks access.

## Scope

**In:**
- Moving to Supabase Postgres.
- `users` and `workspace_members` tables.
- Supabase authentication.
- Row-level security keyed on `workspace_id`.
- Per-workspace sender settings and secrets.

**Out:** billing, plans and usage limits. These get their own plan once there is a paying second customer.

## Tasks

### 6.1 Move to Supabase Postgres

- [ ] Provision the Supabase project, then run `alembic upgrade head` against it. This should need no schema changes: CI has tested Postgres since Phase 1.
- [ ] `scripts/sqlite_to_postgres.py` copies the data table by table in dependency order, then checks row counts and checksums per table.
- [ ] Switch `DATABASE_URL` and keep the SQLite file as a read-only backup.

**Done when:** row counts and checksums match, and the pipeline runs against Postgres.

### 6.2 Users and membership

- [ ] Add migration `00NN_users_and_members`:
  - `users`: id, email, created_at.
  - `workspace_members`: workspace_id, user_id, role (`owner` or `operator`), unique per pair.

  Update [../SCHEMA.md](../SCHEMA.md) in the same PR.
- [ ] Replace the single local login with Supabase Auth JWT validation in FastAPI. The workspace comes from the user's membership, never from client input alone.
- [ ] Change the `events.actor` value from `'operator'` to `'user:<id>'`.

**Done when:** API tests cover membership checks and a forbidden cross-workspace request.

### 6.3 Row-level security

- [ ] Enable RLS on every table, with the policy `workspace_id = current_setting('app.workspace_id')`.
- [ ] The repository layer sets `app.workspace_id` once per transaction.
- [ ] The worker and the scheduler handle one workspace per unit of work.

**Done when:** a test with application-level scoping removed still returns no foreign rows.

### 6.4 Per-workspace configuration

- [ ] Sender profile, campaigns, country policies, mailboxes and caps are already per workspace (schema v1). Provider keys move out of the shared `.env` into a secret store, referenced by name per workspace (`credentials_ref`).
- [ ] Spend is reported per workspace from `provider_calls`.

## Gate record

- Date:
- Migration checksums:
- Isolation test results:
- Checked by:
