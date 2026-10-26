---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-27 (5f6dee4)
applies_to: Phase 6
---

# Architecture decision records

An ADR records one architecturally significant decision: the context, what was decided, what it costs, and what was rejected. These follow [MADR](https://adr.github.io/madr/) in a shortened form ([template](../_templates/adr.md)).

**When to write one.** Write an ADR when a decision changes the structure (layers, processes, data stores), a quality attribute (safety, cost, recoverability), a dependency or platform, an interface others rely on, or how the system is built and deployed. Product rules and compliance policy go in [PLAN.md](../../PLAN.md) instead; an ADR may implement one (for example 0020 implements the country-rule skip).

**Rules.**

- An accepted ADR is never edited, except its `status` line.
- To change a decision, write a new ADR that supersedes it, and mark the old one `superseded by NNNN`.
- Numbers are never reused.
- Dates: 0001–0013 were decided in the plan approved on 2026-10-16, and were first committed with the Phase 0–3 code in c3d3228 (#1). Later records carry the date of the commit that introduced them.
- An ADR whose consequences include a known gap links the [register](../tech-debt-and-risks.md) entry.

## Index

| ADR | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-modular-monolith.md) | One modular monolith in layers | Accepted | 2026-10-16 |
| [0002](0002-the-table-is-the-queue.md) | The companies table is the work queue; the runs table queues runs | Accepted | 2026-10-16 |
| [0003](0003-sqlalchemy-alembic-sqlite-and-postgres.md) | SQLAlchemy 2 and Alembic over SQLite in development and Postgres in production | Accepted | 2026-10-16 |
| [0004](0004-langgraph-only-in-research-and-copy.md) | LangGraph only inside Research and Copy, as stateless subgraphs | Accepted | 2026-10-16 |
| [0005](0005-metered-decorator-and-ledger.md) | Every paid call goes through a Metered decorator that commits its own ledger row | Accepted | 2026-10-16 |
| [0006](0006-no-transaction-across-network.md) | No database transaction across a network call; one short write per lead with optimistic locking | Accepted | 2026-10-16 |
| [0007](0007-state-machines-emit-events.md) | Status changes only through transition tables, each writing an event | Accepted | 2026-10-16 |
| [0008](0008-ports-and-adapters.md) | Vendors behind ports; vendor JSON never leaves its adapter | Accepted | 2026-10-16 |
| [0009](0009-human-approval-and-imap-drafts.md) | A human approves every first email, and the engine only saves drafts over IMAP | Accepted | 2026-10-16 |
| [0010](0010-money-ids-and-time.md) | Integer micro-USD for money, UUIDv7 strings for ids, UTC for time | Accepted | 2026-10-16 |
| [0011](0011-operator-input-wins.md) | Operator input wins: the engine never overwrites a field the operator set | Accepted | 2026-10-16 |
| [0012](0012-server-side-safety-gates.md) | Safety gates are server-side and checked again before every draft or send | Accepted | 2026-10-16 |
| [0013](0013-single-operator-signed-sessions.md) | One operator, an Argon2 password and a signed stateless session cookie | Accepted | 2026-10-16 |
| [0014](0014-web2-replaces-web.md) | web2 replaces the first web app | Accepted | 2026-10-19 |
| [0015](0015-one-image-built-on-the-vm.md) | One Docker image, built on the VM, run as three containers | Accepted | 2026-10-19 |
| [0016](0016-doppler-for-secrets.md) | Secrets come from Doppler at container start | Accepted | 2026-10-19 |
| [0017](0017-supabase-session-pooler.md) | Supabase Postgres through the session pooler, with psycopg 3 and a small pool | Accepted | 2026-10-19 |
| [0018](0018-additive-only-migrations.md) | Migrations are additive, so the previous release can run on the newer schema | Accepted | 2026-10-19 |
| [0019](0019-policy-block-holds-never-suppresses.md) | A country-rule block found by a guard holds the lead; only suppression ends it | Accepted | 2026-10-21 |
| [0020](0020-policy-skip-is-a-tail-from-a-stage.md) | Skipping a country rule is per lead, from one stage onward, or for the whole workspace | Accepted | 2026-10-21 |
| [0021](0021-skips-acknowledged-at-approval.md) | Every skipped check is acknowledged at approval, and never sent automatically | Accepted | 2026-10-21 |
| [0022](0022-consent-belongs-to-the-recipient.md) | Consent belongs to the person who gave it | Accepted | 2026-10-20 |
| [0023](0023-discovery-stores-websites-unconfirmed-people.md) | Discovery stores websites, not names; searched people are confirmed by their employer | Accepted | 2026-10-21 |
| [0024](0024-row-level-security-and-least-privilege-roles.md) | Row-level security and three least-privilege Postgres roles | Accepted | 2026-10-23 |
| [0025](0025-tenant-bound-foreign-keys-and-multi-workspace-worker.md) | Composite tenant-bound foreign keys, and one worker scheduling every workspace | Accepted | 2026-10-23 |
| [0026](0026-revocable-sessions-and-fixed-permission-model.md) | Revocable, hashed sessions replace signed stateless sessions; permissions, not roles, gate every route | Accepted | 2026-10-23 |
| [0027](0027-credits-charged-once-per-lead-per-step.md) | A plan's credit for a step is charged once per lead, except rewrites, which charge every time | Accepted | 2026-10-24 |
| [0028](0028-encrypted-credentials-and-oauth-for-customer-mailboxes.md) | Encrypted-at-rest credentials, OAuth for Microsoft/Google, and an SSRF guard for customer-supplied IMAP hosts | Accepted | 2026-10-23 |
| [0029](0029-shared-lead-directory-with-no-contributor-attribution.md) | A cross-workspace verified lead directory, with attribution structurally absent rather than filtered out | Accepted | 2026-10-26 |
| [0030](0030-rules-based-inbox-classification-no-model.md) | Reply classification is rules-only until a later phase, and only two categories act automatically | Accepted | 2026-10-26 |
