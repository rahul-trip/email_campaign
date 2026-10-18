# Delivery Phases

The engine is built in seven phases. Each phase ships something usable and ends at a **gate**. A gate is a check anyone on the team can run. The next phase starts only after the gate passes; Phases 0 and 1 are the one exception and can run at the same time.

The order follows the plan: **schema, then relationships, then backend engine, then frontend**. The design behind each phase is in [../PLAN.md](../PLAN.md); the data model is in [../SCHEMA.md](../SCHEMA.md).

| Phase | Document | Delivers | Gate | Depends on |
|---|---|---|---|---|
| 0 | [Fix and bake-off](phase-0-fix-and-bakeoff.md) | Legacy duplicate-draft bug fixed; repo cleaned; provider ports and adapters; vendor bake-off | A rerun makes no duplicate drafts; the waterfall chain is chosen from data | — |
| 1 | [Schema and persistence](phase-1-schema-and-persistence.md) | `outbound/` skeleton, 17 tables, migrations, domain core, repositories, seeds, legacy import | Migrations pass up and down on SQLite and Postgres; the 10 xlsx rows are imported; the import is idempotent | — (runs alongside 0) |
| 2 | [Engine on the CLI](phase-2-engine-on-cli.md) | Runner, all stages from intake to draft, Sent-folder sync, Datasette view; `agent/` retired | 8 of 10 touch-1 emails sent without edits; a rerun makes zero paid calls | 0, 1 |
| 3 | [API and web app](phase-3-api-and-web-app.md) | FastAPI over the services, React app, intake webhook | Nothing reaches the mailbox without approval in the web app | 2 |
| 4 | [Close the loop](phase-4-close-the-loop.md) | Just-in-time follow-ups, reply triage, bounces, referrals, opt-outs, forget, reply webhook | A reply stops the sequence; a referral becomes a new contact automatically | 3 |
| 5 | [Automated sending](phase-5-automated-sending.md) | Sending gateway, send window, breaker, DNS and warm-up preflight | Send switch turns on only after gates 2 and 4, warm-up, and legal sign-off | 4 |
| 6 | [SaaS-ready](phase-6-saas-ready.md) | Supabase Postgres, authentication, row-level security | A second workspace runs with no data crossover | 2 (can move earlier) |

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
| 4 | Not started | |
| 5 | Not started | |
| 6 | Not started | |

**Next:** [Phase 3b](phase-3b-hardening.md), which also closes the gates of Phases 0, 2 and 3 with a live run. Phase 0 needs the 30 known contacts and the bake-off run; Phases 2 and 3 list their steps under "Closing the phase". Phase 4 starts after that.

**Test suite (2026-10-18):** 1,236 Python tests pass on SQLite and on PostgreSQL 16.2; the Playwright browser test passes. CI has not run yet because there is no remote repository.

## Engineering rules for every phase

The binding versions of these rules are in [../../CLAUDE.md](../../CLAUDE.md). In short:

- Dependencies point down the layers only, and the domain core has no I/O.
- Vendor JSON never gets past an adapter.
- Every paid call goes through `Metered`.
- Status changes only happen through the state machines.
- No database transaction is held open across a network call.
- Every query is scoped by `workspace_id`.
- Code is typed and passes ruff and mypy.
- No test calls the network.
- Don't build what the current phase doesn't need.
