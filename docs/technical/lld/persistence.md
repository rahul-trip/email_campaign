---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Persistence

**Code:** `outbound/db/` · **Layer:** db (above domain; independent of providers) · **Tests:** `tests/db/`

## Purpose

The persistence layer stores and loads the system's state through repositories that return domain entities, never ORM rows. Each change happens inside one short unit of work. It exists as a layer so that no stage, service or entry point writes SQL, and so that the safety rules that belong next to the data (workspace scoping, legal transitions, operator input, optimistic locking, events) cannot be skipped.

## Responsibilities

- The SQLAlchemy models for the 17 tables, and the shared columns (`id`, `workspace_id`, `created_at`, `updated_at`).
- Column types that behave the same on SQLite and Postgres.
- Engine and session creation, including the Postgres connection pool.
- The unit of work: one session, every repository bound to it, explicit commit.
- One repository per aggregate, which scopes every query by workspace.
- Status transitions: check the state machine, then write the event.
- Field changes: honour `manual_fields`, then write the event.
- Optimistic locking with `row_version`.
- Erasure, deletion and reports.
- Running Alembic from code.

**Not its job:**

- deciding *when* to write (runner, services);
- business rules (domain);
- migrations policy ([migrations](../data/migrations.md)).

## Public interface

| Symbol | Kind | What it does |
|---|---|---|
| `outbound/db/session.py::make_engine` | function | Creates the engine for a URL, with the SQLite pragmas or a Postgres pool |
| `outbound/db/session.py::make_session_factory` | function | A `sessionmaker` with `expire_on_commit=False` |
| `outbound/db/session.py::normalise_url` | function | Rewrites `postgres://` and `postgresql://` to `postgresql+psycopg://` |
| `outbound/db/uow.py::UnitOfWorkFactory` | class | `factory(workspace_id)` returns a `UnitOfWork`; `factory.admin()` returns an `AdminUnitOfWork` |
| `outbound/db/uow.py::UnitOfWork` | context manager | One session. Attributes `companies`, `contacts`, `emails`, `notes`, `consents`, `messages`, `imports`, `suppressions`, `policies`, `campaigns`, `mailboxes`, `runs`, `calls`, `erasure`, `reports`, `events`; `commit()`, `rollback()`, `workspace_settings()` |
| `outbound/db/uow.py::AdminUnitOfWork` | context manager | The one unscoped table: `workspaces` |
| `outbound/db/errors.py::NotFound` | exception | A row that does not exist **in this workspace** |
| `outbound/db/errors.py::ConcurrencyConflict` | exception | A stale `row_version`, from an explicit check or SQLAlchemy's `StaleDataError` |
| `outbound/db/migrate.py` | functions | `upgrade`, `downgrade`, `current_revision`, `head_revision`, `generate` |
| `outbound/db/types.py` | column types | `Json` (JSONB on Postgres, text on SQLite), `UtcDateTime` (refuses naive datetimes, restores UTC on SQLite), enum columns with a named `CHECK`, `utcnow` |

Code outside `outbound/db` may not import `outbound.db.models`; a ruff `banned-api` rule enforces this.

## Repositories

All but `WorkspaceRepository` extend `ScopedRepository`.

| Repository (attribute) | Owns | Notable behaviour |
|---|---|---|
| `CompanyRepository` (`companies`) | `companies` | `due(status, limit, now)` is the work queue; `transition(...)` checks the version and the state machine, and writes the event; `update_fields` only for `EDITABLE_FIELDS`; `search`, `due_held`, `count_by_status`, `by_domain` |
| `ContactRepository` (`contacts`) | `contacts` | `add`, `transition` (no version check), `make_first`, `update_fields` |
| `ContactEmailRepository` (`emails`) | `contact_emails` | `add`, `by_address`, `set_primary` (one primary per contact), `set_verification_skipped` (writes the event), `transition` |
| `NoteRepository` (`notes`) | `notes` | Append-only |
| `ConsentRepository` (`consents`) | `consents` | `add` keeps one active consent per basis; `withdraw`; `has_active` |
| `MessageRepository` (`messages`) | `messages` | `create`, `transition` (version check; extra fields limited to `TRANSITION_FIELDS`), `edited_examples` (few-shot for copy), `rfc_id_taken` |
| `ImportRepository` (`imports`) | `import_batches`, `import_rows` | `create_batch`, `add_row`, `settle_row`, `rows_with_status`, `batch_exists` (webhook idempotency) |
| `SuppressionRepository` (`suppressions`) | `suppressions` | Stores hashes only; `blocks(email)` checks the address and its registrable domain |
| `CountryPolicyRepository` (`policies`) | `country_policies` | `upsert` bumps `version` on a real change; `add_if_missing` (seed never overwrites an edit); `delete` |
| `CampaignRepository`, `MailboxRepository` (`campaigns`, `mailboxes`) | `campaigns`, `mailboxes` | `by_name`; `set_dns_check` |
| `WorkspaceRepository` (`admin.workspaces`) | `workspaces` | Unscoped; used only through `AdminUnitOfWork` and `UnitOfWork.workspace_settings` |
| `RunRepository` (`runs`) | `runs` | `queue`, `claim_next` (`FOR UPDATE SKIP LOCKED`), `mark_running`, `start`, `cancel`, `finish`, `cost_of` |
| `ProviderCallRepository` (`calls`) | `provider_calls` | `record`, `cached_response`, `spend_since`, `spend_on_company`, `for_company` |
| `ErasureRepository` (`erasure`) | Personal data in every table | `scrub_contact`, `delete_company`, `delete_contact` ([data lifecycle](../data/data-lifecycle.md)) |
| `ReportRepository` (`reports`) | Read-only aggregates | `touch_one`, `company_counts`, `spend_by_provider`, `spend_by_company`, `call_outcomes` |
| `EventRepository` (`events`) | `events` | `append`, `for_entity`, `for_entities`. One instance is shared by every repository in a unit of work |

## How it works

### A unit of work

```python
with container.uow(workspace_id) as uow:
    company = uow.companies.get(company_id)          # NotFound if not in this workspace
    uow.companies.transition(company.id, CompanyStatus.QUALIFIED,
                             expected_version=company.row_version, reason="…")
    uow.commit()                                    # nothing is written without this
```

- `__enter__` opens a session and binds every repository, all sharing one `EventRepository`.
- `__exit__` rolls back if an exception escaped, and always closes the session.
- `commit()` maps SQLAlchemy's `StaleDataError` to `ConcurrencyConflict`.
- Sessions use `expire_on_commit=False`, so the entities built from rows stay readable after commit.

### Scoping

`ScopedRepository._row(model, id)` filters by **both** `id` and `workspace_id`, so another workspace's row is simply `NotFound`. Every list query adds the same filter. This is binding rule 6, and Phase 6's row-level security will key on the same column.

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

### Engines

| | SQLite (development, tests) | Postgres (production) |
|---|---|---|
| URL | `sqlite:///<SQLITE_PATH>` | `POSTGRES_URL`, rewritten to `postgresql+psycopg://` |
| Pool | SQLAlchemy default | `pool_size = DATABASE_POOL_SIZE` (5), `max_overflow = 0`, `pool_pre_ping`, `pool_recycle = 300` |
| On connect | `foreign_keys=ON`, `busy_timeout=5000`, `journal_mode=WAL` | — |
| JSON | text | JSONB |
| `SKIP LOCKED` | ignored | honoured |

Migrations use their own engine with no pool (`outbound/db/migrations/env.py`). Pool sizing against the Supabase pooler limit is in [capacity and limits](../operations/capacity-and-limits.md) ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)).

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

`DATABASE_BACKEND`, `SQLITE_PATH`, `POSTGRES_URL`, `DATABASE_URL`, `DATABASE_POOL_SIZE`. See the [configuration reference](../operations/configuration-reference.md) and [configuration and bootstrap](configuration-and-bootstrap.md).

## Observability

This layer emits no log events (SQLAlchemy's own logs are raised to WARNING). It writes the `events` table: `status_changed`, `field_changed`, `created`, consent, skip, suppression and erasure events. See [observability](../operations/observability.md#the-events-table).

## Security and privacy

- **Scoping** is the tenant boundary.
- **Suppressions** store hashes only.
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

The whole folder runs on SQLite by default and on Postgres when `TEST_DATABASE_URL` is set (`tests/db/conftest.py`).

## Known limitations

- No `row_version` on `contacts`, `contact_emails` or `runs`; run transitions not checked ([R-15](../tech-debt-and-risks.md#r-15--p2--correctness-runs-and-three-tables-bypass-the-usual-guards)).
- No retention ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)).
- JSON columns are untyped dicts (Phase 3b deferred item).

## Extending it

- **A column:** follow [add a migration](../guides/add-a-migration.md).
- **A query:** add a method to the owning repository. It must filter by `workspace_id` and return entities. Do not add a generic base-repository hierarchy ([CLAUDE.md](../../../CLAUDE.md), "Do not over-engineer").

## Planned

- Phase 6 adds `users` and `workspace_members`, and row-level security on `workspace_id`: [phase-6-saas-ready.md](../../phases/phase-6-saas-ready.md).

## How to refresh this page

```bash
grep -n "class .*Repository" outbound/db/repositories/*.py
grep -n "manual_fields\|version_id_col" outbound/db/models.py
sed -n '/def make_engine/,/^def /p' outbound/db/session.py
uv run pytest tests/db -q
```
