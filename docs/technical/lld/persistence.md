---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-27 (5f6dee4)
applies_to: Phase 6a/6b/6d
---

# Persistence

**Code:** `outbound/db/` · **Layer:** db (above domain; independent of providers) · **Tests:** `tests/db/`

## Purpose

The persistence layer stores and loads the system's state through repositories that return domain entities, never ORM rows. Each change happens inside one short unit of work. It exists as a layer so that no stage, service or entry point writes SQL, and so that the safety rules that belong next to the data (workspace scoping, legal transitions, operator input, optimistic locking, events) cannot be skipped. As of Phase 6a there are **three** units of work, not one, because tenant data, platform-wide data, and identity data each have a different scoping story — see [tenancy and isolation](tenancy-and-isolation.md) for why.

## Responsibilities

- The SQLAlchemy models for the 35 tables (up from 17 before the SaaS transformation), and the shared columns (`id`, `workspace_id` where tenant-scoped, `created_at`, `updated_at`).
- Column types that behave the same on SQLite and Postgres.
- Engine and session creation, including the Postgres connection pool, for three separate connections (owner/migrate, `outbound_app`, `outbound_platform`).
- Three units of work: tenant (`UnitOfWork`, one workspace), platform (`PlatformUnitOfWork`, cross-workspace reads plus platform-only writes), identity (`IdentityUnitOfWork`, users/memberships/sessions/tokens/audit — platform data with no row-level security at all).
- One repository per aggregate, which scopes every tenant query by workspace, and relies on Postgres row-level security as the hard backstop ([tenancy and isolation](tenancy-and-isolation.md)).
- Status transitions: check the state machine, then write the event.
- Field changes: honour `manual_fields`, then write the event.
- Optimistic locking with `row_version`.
- Erasure, deletion and reports.
- Running Alembic from code, as the one role (`outbound_migrate`/owner) allowed to alter the schema.

**Not its job:**

- deciding *when* to write (runner, services);
- business rules (domain);
- migrations policy ([migrations](../data/migrations.md));
- the row-level security policies and role grants themselves, which live in the migration and are explained in [tenancy and isolation](tenancy-and-isolation.md), not repeated here.

## Public interface

| Symbol | Kind | What it does |
|---|---|---|
| `outbound/db/session.py::make_engine` | function | Creates the engine for a URL, with the SQLite pragmas or a Postgres pool |
| `outbound/db/session.py::make_session_factory` | function | A `sessionmaker` with `expire_on_commit=False` |
| `outbound/db/session.py::normalise_url` | function | Rewrites `postgres://` and `postgresql://` to `postgresql+psycopg://` |
| `outbound/db/uow.py::UnitOfWorkFactory` | class | `factory(workspace_id, read_only=False)` returns a tenant `UnitOfWork`, with the `app.workspace_id` session setting for row-level security |
| `outbound/db/uow.py::UnitOfWork` | context manager | One session, scoped to one workspace. Attributes `companies`, `contacts`, `emails`, `notes`, `consents`, `messages`, `inbound`, `directory`, `imports`, `suppressions`, `policies`, `campaigns`, `mailboxes`, `credentials`, `usage`, `platform_settings`, `runs`, `calls`, `erasure`, `reports`, `own_workspace`, `events`; `commit()`, `rollback()`, `workspace()`, `workspace_settings()` |
| `outbound/db/platform.py::PlatformUnitOfWorkFactory`, `PlatformUnitOfWork` | class, context manager | The cross-workspace connection (`outbound_platform`, read-only on tenant tables). Attributes `vendor_keys`, `directory` (admin side), `workspaces`, `scheduler` (`SchedulerQueries`), `figures`, `audit`, `plans`, `settings` |
| `outbound/db/identity.py::IdentityUnitOfWorkFactory`, `IdentityUnitOfWork` | class, context manager | Platform tables with no `workspace_id` at all. Attributes `users`, `memberships`, `tokens`, `sessions`, `audit` — see [identity and access](identity-and-access.md) |
| `outbound/db/errors.py::NotFound` | exception | A row that does not exist **in this workspace** |
| `outbound/db/errors.py::ConcurrencyConflict` | exception | A stale `row_version`, from an explicit check or SQLAlchemy's `StaleDataError` |
| `outbound/db/migrate.py` | functions | `upgrade`, `downgrade`, `current_revision`, `head_revision`, `generate` |
| `outbound/db/types.py` | column types | `Json` (JSONB on Postgres, text on SQLite), `UtcDateTime` (refuses naive datetimes, restores UTC on SQLite), enum columns with a named `CHECK`, `utcnow` |

Code outside `outbound/db` may not import `outbound.db.models`; a ruff `banned-api` rule enforces this.

## Repositories

**Tenant (through `UnitOfWork`), scoped by `workspace_id`:**

| Repository (attribute) | Owns | Notable behaviour |
|---|---|---|
| `CompanyRepository` (`companies`) | `companies` | `due(status, limit, now)` is the work queue; `transition(...)` checks the version and the state machine, and writes the event; `update_fields` only for `EDITABLE_FIELDS`; `search`, `due_held`, `count_by_status`, `by_domain` |
| `ContactRepository` (`contacts`) | `contacts` | `add`, `transition` (no version check), `make_first`, `update_fields` |
| `ContactEmailRepository` (`emails`) | `contact_emails` | `add`, `by_address`, `set_primary` (one primary per contact), `set_verification_skipped` (writes the event), `transition` |
| `NoteRepository` (`notes`) | `notes` | Append-only |
| `ConsentRepository` (`consents`) | `consents` | `add` keeps one active consent per basis; `withdraw`; `has_active` |
| `MessageRepository` (`messages`) | `messages` | `create`, `transition` (version check; extra fields limited to `TRANSITION_FIELDS`), `edited_examples` (few-shot for copy), `rfc_id_taken` |
| `InboundRepository` (`inbound`) | `inbound_messages` | `add`, `known(rfc_message_id)`, `latest(mailbox_id)`, `mark_handled` — see [inbox and opt-outs](inbox-and-opt-outs.md) |
| `DirectoryRepository` (`directory`) | A workspace's own view of shared directory facts | `find_email`, `verified_month`, `holds`, `report` — see [the lead directory](lead-directory.md) |
| `ImportRepository` (`imports`) | `import_batches`, `import_rows` | `create_batch`, `add_row`, `settle_row`, `rows_with_status`, `batch_exists` (webhook idempotency) |
| `SuppressionRepository` (`suppressions`) | `suppressions` | Stores hashes only; `blocks(email)` checks the address and its registrable domain |
| `CountryPolicyRepository` (`policies`) | `country_policies` | `upsert` bumps `version` on a real change; `add_if_missing` (seed never overwrites an edit); `delete` |
| `CampaignRepository`, `MailboxRepository` (`campaigns`, `mailboxes`) | `campaigns`, `mailboxes` | `by_name`; `set_dns_check` |
| `CredentialRepository` (`credentials`) | `credentials` | Seals/opens mailbox and webhook secrets through the `Keyring` passed to the unit of work — see [mailboxes and OAuth](mailboxes-and-oauth.md) |
| `UsageRepository` (`usage`) | `usage_events` | Charges a step, respecting the once-per-lead unique index; counts used this period — see [plans, credits and admin](plans-credits-and-admin.md) |
| `PlatformSettingsRepository` (`platform_settings`, read via tenant session) | `workspace_plans`, `entitlement_overrides`, `credit_grants` | Read-only for a workspace's own Plan & Usage view; writes go through the platform unit of work |
| `OwnWorkspaceRepository` (`own_workspace`) | `workspaces` (this workspace's own row only) | `get()` — the one way a tenant session reads `workspaces`, via `uow.workspace()`/`workspace_settings()` |
| `RunRepository` (`runs`) | `runs` | `queue`, `claim_next` (`FOR UPDATE SKIP LOCKED`), `mark_running`, `start`, `cancel`, `finish`, `fail_stale`, `cost_of` |
| `ProviderCallRepository` (`calls`) | `provider_calls` | `record`, `cached_response`, `spend_since`, `spend_on_company`, `for_company` |
| `ErasureRepository` (`erasure`) | Personal data in every table | `scrub_contact`, `delete_company`, `delete_contact` ([data lifecycle](../data/data-lifecycle.md)) |
| `ReportRepository` (`reports`) | Read-only aggregates | `touch_one`, `company_counts`, `spend_by_provider`, `spend_by_company`, `call_outcomes` |
| `EventRepository` (`events`) | `events` | `append`, `for_entity`, `for_entities`. One instance is shared by every repository in a unit of work |

**Platform (through `PlatformUnitOfWork`), cross-workspace, no `workspace_id` filter:**

| Repository (attribute) | Owns | Notable behaviour |
|---|---|---|
| `WorkspaceRepository` (`workspaces`) | `workspaces` | Create, resolve by name/slug, set status/access — see [tenancy and isolation](tenancy-and-isolation.md) |
| `SchedulerQueries` (`scheduler`) | Ids only, never rows | `active_workspaces`, `with_queued_runs`, `with_stale_runs` — the worker's entire cross-tenant view, see [runner and worker](runner-and-worker.md) |
| `PlanAdminRepository` (`plans`) | `workspace_plans`, `entitlement_overrides`, `credit_grants` | The admin console's write side — see [plans, credits and admin](plans-credits-and-admin.md) |
| `VendorKeyRepository` (`vendor_keys`) | Platform vendor keys | Encrypted the same way as mailbox credentials |
| `DirectoryAdminRepository` (`directory`) | Shared directory facts, platform side | Folding in verified facts, retention sweep, dispute review |
| `AdminQueries` (`figures`) | Cross-workspace aggregates | Admin console figures (usage, directory savings) |
| `AuditRepository` (`audit`) | `audit_log` | Shared with the identity unit of work — see [identity and access](identity-and-access.md) |
| `PlatformSettingsRepository` (`settings`) | `platform_settings` | The platform's own kill switch and settings |

**Identity (through `IdentityUnitOfWork`), platform data, no `workspace_id` at all:**

| Repository (attribute) | Owns | Notable behaviour |
|---|---|---|
| `UserRepository` (`users`) | `users` | See [identity and access](identity-and-access.md) |
| `MembershipRepository` (`memberships`) | `memberships` | `(workspace_id, user_id, role)` — the only identity table with a `workspace_id` column, kept here rather than in a tenant unit of work because it is not *owned* by either side alone |
| `AuthTokenRepository` (`tokens`) | `auth_tokens` | Invite/reset/remove-my-data, one-time, hash-stored |
| `SessionRepository` (`sessions`) | `sessions` | Revocable login sessions |
| `AuditRepository` (`audit`) | `audit_log` | Same table and repository class the platform unit of work uses |

## How it works

### A unit of work

```python
with container.uow(workspace_id) as uow:              # tenant: sets app.workspace_id
    company = uow.companies.get(company_id)          # NotFound if not in this workspace
    uow.companies.transition(company.id, CompanyStatus.QUALIFIED,
                             expected_version=company.row_version, reason="…")
    uow.commit()                                    # nothing is written without this

with container.platform() as platform:                # cross-workspace, read-mostly
    due = platform.scheduler.with_queued_runs(now)

with container.identity() as identity:                # no workspace_id at all
    user = identity.users.by_email(email)
```

- `container.uow(workspace_id, read_only=False)`, `container.platform()` and `container.identity()` are the three entry points ([`outbound/bootstrap.py::Container`](../lld/configuration-and-bootstrap.md)) — a stage or service takes whichever one matches what it needs, never constructs a session directly.
- `__enter__` opens a session and binds every repository, all sharing one `EventRepository` (tenant) or the shared `AuditRepository` (platform/identity).
- `__exit__` rolls back if an exception escaped, and always closes the session.
- `commit()` maps SQLAlchemy's `StaleDataError` to `ConcurrencyConflict`.
- Sessions use `expire_on_commit=False`, so the entities built from rows stay readable after commit.

### Scoping

`ScopedRepository._row(model, id)` filters by **both** `id` and `workspace_id`, so another workspace's row is simply `NotFound`. Every list query adds the same filter. This is binding rule 6, and it is no longer the only line of defence: the same `workspace_id` is also what Postgres row-level security keys on (`current_setting('app.workspace_id')`, set per-transaction by the session's `after_begin` listener), so a repository bug that forgets the filter still returns nothing, rather than another tenant's rows. See [tenancy and isolation](tenancy-and-isolation.md) for the full mechanism.

### Entities, not rows

`outbound/db/repositories/base.py::snapshot` copies a row into its frozen dataclass by matching field names. Callers never hold an ORM object, so there is no lazy loading after a session closes and no accidental write.

### Operator input wins

`ScopedRepository._apply_changes` refuses a field not in the repository's editable set, then for each changed field:

| Actor | Field in `manual_fields`? | Result |
|---|---|---|
| operator | either | Applied; the field is added to `manual_fields`; `field_changed` event with `applied: true` |
| engine (system or a provider) | no | Applied; `field_changed` with `applied: true` |
| engine | yes | **Not applied**; `field_changed` with `applied: false` and the engine's value |

Only `companies` and `contacts` have `manual_fields`.

### Optimistic locking

`companies.row_version` and `messages.row_version` are SQLAlchemy `version_id_col`s. Every UPDATE includes `WHERE row_version = <old>` and increments it. In addition, `transition` and `update_fields` take an `expected_version` from the caller and compare it before changing anything (`_check_version`), so a decision made on a stale read is refused even before the UPDATE. `contacts`, `contact_emails` and `runs` have no version column, so concurrent edits to them are last-writer-wins ([R-15](../tech-debt-and-risks.md#r-15--p2--correctness-runs-and-three-tables-bypass-the-usual-guards)).

### Transitions

`CompanyRepository.transition` does the following, in order:

1. Load the row (scoped).
2. Check the version.
3. `COMPANY.check(current, target)`.
4. Require a `hold_reason` for `held`, and a known `failed_stage` for `failed`.
5. Set the status and its side fields. Moving to `failed` increments `attempts`.
6. Append a `status_changed` event with `from`, `to`, `reason`, `hold_reason`, `failed_stage` and `error`.

The other lifecycles follow the same pattern; [state machines](../hld/state-machines.md) lists which check versions. `RunRepository` uses `RUN.allows` only and writes no event ([R-15](../tech-debt-and-risks.md#r-15--p2--correctness-runs-and-three-tables-bypass-the-usual-guards)).

### Three engines, one database (on Postgres)

| | SQLite (development, tests) | Postgres (production) |
|---|---|---|
| URL(s) | One file for all three settings | `DATABASE_URL` (`outbound_app`), `PLATFORM_DATABASE_URL` (`outbound_platform`), `MIGRATE_DATABASE_URL` (owner) — each rewritten to `postgresql+psycopg://` |
| Pool | SQLAlchemy default, one per process | `pool_size = DATABASE_POOL_SIZE` (5), `max_overflow = 0`, `pool_pre_ping`, `pool_recycle = 300`, per connection |
| On connect | `foreign_keys=ON`, `busy_timeout=5000`, `journal_mode=WAL` | — |
| JSON | text | JSONB |
| `SKIP LOCKED` | ignored | honoured |
| Row-level security | None — isolation rests on scoping alone | Enforced per role; see [tenancy and isolation](tenancy-and-isolation.md) |

Migrations use their own engine with no pool, connected as the owner (`outbound/db/migrations/env.py`). Three processes (api, worker) × up to two pools each (tenant + platform) against the Supabase session pooler's connection ceiling is in [capacity and limits](../operations/capacity-and-limits.md) ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)).

### Naming and types

`outbound/db/base.py::NAMING_CONVENTION` gives every index and constraint a stable name, so Alembic produces identical migrations on both databases. Mixins: `Identified` (UUIDv7 `id`), `Scoped` (+ `workspace_id`), `AppendOnly` (+ `created_at`), `Mutable` (+ `updated_at`).

## Invariants

- No row is read or written without its workspace.
- A status never changes without its transition being legal and its event being written in the same transaction.
- An operator value is never overwritten by the engine.
- A write based on a stale `companies` or `messages` read fails.

## Errors

| Error | Cause | Seen as |
|---|---|---|
| `NotFound` | No such row in this workspace | API `404 not_found`; runner skips a deleted lead |
| `ConcurrencyConflict` | Stale `row_version` | API `409 version_conflict`; runner: the lead is skipped this run |
| `IllegalTransition` | Not in the table | API `409 action_not_allowed` |
| `IntegrityError` | A unique or check constraint | Caught where it is expected (webhook duplicates, intake); otherwise a 500 |
| `ValueError` | A field outside the editable set | A programming error |

## Configuration

`DATABASE_BACKEND`, `SQLITE_PATH`, `POSTGRES_URL`/`POSTGRES_PLATFORM_URL`/`POSTGRES_MIGRATE_URL`, `DATABASE_URL`/`PLATFORM_DATABASE_URL`/`MIGRATE_DATABASE_URL`, `DATABASE_POOL_SIZE`, `SECRETS_KEYS`. See the [configuration reference](../operations/configuration-reference.md) and [configuration and bootstrap](configuration-and-bootstrap.md).

## Observability

This layer emits no log events (SQLAlchemy's own logs are raised to WARNING). It writes the `events` table: `status_changed`, `field_changed`, `created`, consent, skip, suppression and erasure events, plus `audit_log` for identity and admin actions. See [observability](../operations/observability.md#the-events-table).

## Security and privacy

- **Row-level security plus scoping together** are the tenant boundary, not scoping alone ([tenancy and isolation](tenancy-and-isolation.md)).
- **Suppressions** store hashes only.
- **Mailbox and vendor credentials** are AES-256-GCM-encrypted at rest, keyed by `SECRETS_KEYS` ([mailboxes and OAuth](mailboxes-and-oauth.md)).
- **Erasure** blanks every personal column ([data lifecycle](../data/data-lifecycle.md)).
- **TLS to Postgres** depends on `sslmode=require` in the URL ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)).

## Tests

| File | Proves |
|---|---|
| `tests/db/test_migrations.py` | Upgrade, downgrade, re-upgrade; models equal the migrated schema; `CHECK` lists equal enums |
| `tests/db/test_constraints.py` | Every uniqueness and check rule, foreign keys, cascades |
| `tests/db/test_companies_repo.py`, `tests/db/test_people_repo.py`, `tests/db/test_other_repos.py` | Scoping, transitions, `manual_fields`, versions |
| `tests/db/test_session.py` | URL normalising, the backend switch, pool settings |
| `tests/db/test_forget.py`, `tests/db/test_delete_lead.py`, `tests/db/test_privacy.py` | Erasure and deletion, scanning every column |
| `tests/db/test_rls.py` | Row-level security per role, the isolation self-check ([tenancy and isolation](tenancy-and-isolation.md)) |
| `tests/db/test_scheduler.py` | `SchedulerQueries`' ids-only, cross-workspace reads |

The whole folder runs on SQLite by default and on Postgres when `TEST_DATABASE_URL` is set (`tests/db/conftest.py`).

## Known limitations

- No `row_version` on `contacts`, `contact_emails` or `runs`; run transitions not checked ([R-15](../tech-debt-and-risks.md#r-15--p2--correctness-runs-and-three-tables-bypass-the-usual-guards)).
- No retention ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)).
- JSON columns are untyped dicts (a deferred item carried forward from Phase 3b).
- `PLATFORM_DATABASE_URL` falling back to `DATABASE_URL` when unset is correct for SQLite and single-role rehearsal, but would run the scheduler as `outbound_app` in a misconfigured production deployment ([tenancy and isolation](tenancy-and-isolation.md#known-limitations)).

## Extending it

- **A column:** follow [add a migration](../guides/add-a-migration.md).
- **A query:** add a method to the owning repository. It must filter by `workspace_id` (tenant) or go through the platform/identity unit of work as appropriate, and return entities. Do not add a generic base-repository hierarchy ([CLAUDE.md](../../../CLAUDE.md), "Do not over-engineer").
- **A new tenant table:** use `_tenant_fk` for every foreign key to another tenant table, not a plain `ForeignKey`, and add it to the row-level-security isolation test's table list ([tenancy and isolation](tenancy-and-isolation.md)).

## Planned

Usage-based billing integration reading `usage_events` is the natural next consumer of this layer's data, tracked in the [tech-debt register](../tech-debt-and-risks.md).

## How to refresh this page

```bash
grep -n "class .*Repository" outbound/db/repositories/*.py
grep -n "manual_fields\|version_id_col" outbound/db/models.py
sed -n '/def make_engine/,/^def /p' outbound/db/session.py
uv run pytest tests/db -q
```
