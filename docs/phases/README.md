# Delivery Phases

The engine is built in phases 0–6. Phase 6 (SaaS) is split into sub-phases 6a–6g, and its overview is [phase-6-saas-ready.md](phase-6-saas-ready.md). Each phase ships something usable and ends at a **gate**. A gate is a check anyone on the team can run.

The next phase starts only after the gate passes, with two exceptions:
- Phases 0 and 1 can run at the same time.
- 6g and the rest of Phase 4 run in parallel once the alpha has started.

The order follows the plan: **schema, then relationships, then backend engine, then frontend**. The design behind each phase is in [../PLAN.md](../PLAN.md); the data model is in [../SCHEMA.md](../SCHEMA.md).

| Phase | Document | Delivers | Gate | Depends on |
|---|---|---|---|---|
| 0 | [Fix and bake-off](phase-0-fix-and-bakeoff.md) | Legacy duplicate-draft bug fixed; repo cleaned; provider ports and adapters; vendor bake-off | A rerun makes no duplicate drafts; the waterfall chain is chosen from data | — |
| 1 | [Schema and persistence](phase-1-schema-and-persistence.md) | `outbound/` skeleton, 17 tables, migrations, domain core, repositories, seeds, legacy import | Migrations pass up and down on SQLite and Postgres; the 10 xlsx rows are imported; the import is idempotent | — (runs alongside 0) |
| 2 | [Engine on the CLI](phase-2-engine-on-cli.md) | Runner, all stages from intake to draft, Sent-folder sync, Datasette view; `agent/` retired | 8 of 10 touch-1 emails sent without edits; a rerun makes zero paid calls | 0, 1 |
| 3 | [API and web app](phase-3-api-and-web-app.md) | FastAPI over the services, React app, intake webhook | Nothing reaches the mailbox without approval in the web app | 2 |
| 4 | [Close the loop](phase-4-close-the-loop.md) | Just-in-time follow-ups, reply triage, bounces, referrals, opt-outs, forget, reply webhook. **4a** (opt-outs and hard bounces) comes before the SaaS alpha | A reply stops the sequence; a referral becomes a new contact automatically | 3; built after 6d so it is tenant-aware |
| 5 | [Automated sending](phase-5-automated-sending.md) | Sending through each connected mailbox, send window, breaker, DNS and warm-up preflight | Send switch turns on only after gates 2 and 4, warm-up, and legal sign-off | 4, 6c, 6d |
| 6 | [SaaS (alpha track)](phase-6-saas-ready.md) | Overview of 6a–6g: decisions, isolation model, order | A second workspace runs with no data crossover, even with application scoping bypassed | 3b |
| 6a | [Tenancy foundation](phase-6a-tenancy-foundation.md) | Composite FKs, row-level security with least-privilege roles, platform unit of work, services per request, multi-tenant worker | Isolation holds with application scoping patched out; the suite passes as `outbound_app` | 3b |
| 6b | [Identity and access](phase-6b-identity-and-access.md) | Users, invitations, password reset, sessions, admin/member roles, platform admin and superadmin, `/w/{slug}` URLs | Every route tested against every role; invite and reset flows in the browser | 6a |
| 6c | [Onboarding and mailboxes](phase-6c-onboarding-and-mailboxes.md) | Encrypted credentials; IMAP, Microsoft Graph and Gmail adapters; sender identity per mailbox; onboarding wizard; Settings layout | A customer gets a draft into its own M365 and IMAP mailbox using only the browser | 6b |
| 6d | [Plans, limits and admin](phase-6d-plans-limits-and-admin.md) | Per-step credits, grants and access time, waiting and resuming, vendor keys in the database, the admin console | Free plan's 5+5 enforced and resumable; key and limit changes apply without restart; two pilot customers | 6c |
| 6g | [Verified lead directory](phase-6g-lead-directory.md) | Shared verified facts checked first in the email waterfall; reports and reconfirmation; skip option | A fact verified for one customer saves another a paid lookup; nothing reveals who prospected whom | 6d |
| 6e | [Billing](phase-6e-billing.md) | **After the alpha:** payments, trials, open sign-up | Test-mode lifecycle passes | 6d |
| 6f | [Launch readiness](phase-6f-launch-readiness.md) | **After the alpha:** MFA, support role replacing superadmin, Google CASA, directory legal steps, penetration test | Launch checklist signed | 6e |
| 7 | [Later: the backlog](phase-7-later.md) | Everything deliberately left out, each with the need that would pull it in | None until an item is scheduled | — |

## How to work a phase

1. Create a branch named `phase-N/<short-task>` for each task. Keep PRs small: one task, or one coherent group of tasks.
2. Every task lists the files it touches and a **done when** line. A task is done when its tests are green in CI and the done-when line is true.
3. If a task changes behaviour, the same PR updates [../PLAN.md](../PLAN.md). If it changes data, the same PR adds an Alembic migration and updates [../SCHEMA.md](../SCHEMA.md).
4. To close a phase:
   - Run the gate, then write the result (date, numbers, who checked) in that phase's **Gate record** section.
   - Tick the phase in the status table below.

## Status

| Phase | Status | Gate passed on |
|---|---|---|
| 0 | Code complete; most keys now in `.env`; gate waiting on the 30 known contacts and the bake-off run | |
| 1 | Code complete; verified on SQLite and Postgres 16.2; CI not yet run | |
| 2 | Code complete; verified with fake vendors on SQLite and Postgres 16.2; gate waiting on live keys and a real run of 10 emails; `agent/` not yet deleted | |
| 3 | Code complete; API tested, browser test passes against fake vendors; gate waiting on a live run with real keys | |
| 3b | **Planned, next.** [Hardening before live use](phase-3b-hardening.md): 36 gaps from the audit (9 P0) | |
| 4 | Not started (4a planned before the SaaS alpha) | |
| 5 | Not started | |
| 6 | Planned (2026-10-23): SaaS alpha track 6a–6g approved | |
| 6a | **Code complete** (2026-10-23, branch `phase-6/tenancy-foundation`); the Postgres suite passes as `outbound_app`; the gate waits on the database roles in Supabase, a rehearsal on a production copy and a deploy | |
| 6b | **Code complete** (2026-10-23, branch `phase-6/identity-and-access`); every route is tested against every role, and the invite, reset and superadmin flows pass in the browser. The gate waits on a transactional email provider and a deploy | |
| 6c | **Code complete** (2026-10-24, branch `phase-6/onboarding-and-mailboxes`); the suite passes on SQLite and on Postgres as `outbound_app`. The gate waits on live checks with real Microsoft 365, Google and IMAP mailboxes | |
| 6d, 6g | Not started | |
| 6e, 6f | After the alpha | |
| 7 | Backlog, unscheduled | |

**Next:**
1. **Now:** close the Supabase Data API exposure ([phase-3b-hardening.md](phase-3b-hardening.md), E8). It is an operator task in the Supabase dashboard.
2. **[Phase 3b](phase-3b-hardening.md).** It also closes the gates of Phases 0, 2 and 3 with a live run.
   - Phase 0 needs the 30 known contacts and the bake-off run.
   - Phases 2 and 3 list their steps under "Closing the phase".
   - Section 8 lists what 3b must finish before 6a.

**Then the SaaS alpha track:**

```
6a → 6b → 6c → 6d → 4a → ALPHA → (6g ∥ rest of 4) → after the alpha: 6e → 6f → 5
```

Everything else that was left out waits in [Phase 7](phase-7-later.md) until a measured need appears.

**Test suite (2026-10-18):** 1,236 Python tests pass on SQLite and on PostgreSQL 16.2; the Playwright browser test passes. CI has not run yet because there is no remote repository.

## Engineering rules for every phase

The binding versions of these rules are in [../../CLAUDE.md](../../CLAUDE.md). In short:

- Dependencies point down the layers only, and the domain core has no I/O.
- Vendor JSON never gets past an adapter.
- Every paid call goes through `Metered`.
- Status changes only happen through the state machines.
- No database transaction is held open across a network call.
- Every query on a tenant table is scoped by `workspace_id`; from 6a, Postgres row-level security enforces it as well.
- From 6b, every API route declares its permission.
- Code is typed and passes ruff and mypy.
- No test calls the network.
- Don't build what the current phase doesn't need.
