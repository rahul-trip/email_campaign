# CLAUDE.md

Instructions for anyone (human or AI agent) changing code in this repository.

## What this is

This repository is an outbound B2B email engine. It takes target companies, either from the operator or from search, and runs each through the same pipeline:

1. research the company;
2. find and verify a decision-maker's email through a pay-as-you-go waterfall;
3. write a short personalised email;
4. once a human approves it, place it as a draft in the mailbox.

Later phases add follow-ups, reply handling and automatic sending. Phase 6 turns it into a multi-tenant SaaS, starting with an invite-only alpha (`docs/phases/phase-6-saas-ready.md`).

## Source of truth — read these before changing code

| Document | Use it for |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Decisions, architecture, stages, compliance, providers |
| [docs/SCHEMA.md](docs/SCHEMA.md) | The data model: every table, column, constraint and relationship |
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | How the operator uses the app. Update it when a screen, command, status or message changes |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Running it on the VM: Docker image, compose stack, deploy workflow, Doppler, Supabase |
| [docs/design.md](docs/design.md) | Design system & tokens (synced with Stitch project `Design System Generator`) |
| [docs/phases/](docs/phases/README.md) | What to build now: one document per phase, with tasks, files and a gate |

- Work on the current phase only; the phase status table in `docs/phases/README.md` says which one that is.
- A PR that changes behaviour updates `docs/PLAN.md`.
- A PR that changes data adds an Alembic migration and updates `docs/SCHEMA.md`.
- The team reviews in the Claude Doc ["Outbound Engine: End-to-End Plan"](https://claude.ai/code/artifact/4cea76e3-1e09-442e-a719-22299ed78ece). The repo files are what you build from.
- `docs/archive/` contains superseded specs and history. Do not build from it.

## Current state (2026-10-18)

- **Phase 0:** code complete. Most vendor keys are now in the root `.env`; the gate waits on the 30 known contacts and the bake-off run (see `docs/phases/phase-0-fix-and-bakeoff.md`).
- **Phase 1:** code complete and verified on SQLite and on PostgreSQL 16.2. Its CI workflow has not run yet. See `docs/phases/phase-1-schema-and-persistence.md`.
- **Phase 2 (engine on the CLI):** code complete and verified with fake vendors on SQLite and PostgreSQL 16.2 (1,163 tests). The gate (8 of 10 first emails sent unedited, a zero-cost rerun) waits on live keys and a real run. See `docs/phases/phase-2-engine-on-cli.md`, "Closing the phase".
- **Phase 3b (hardening) is next:** `docs/phases/phase-3b-hardening.md` lists the gaps found after Phase 3 and the order to fix them.
  - **Do first, E8:** Supabase's Data API probably exposes the production tables. Turn it off and revoke the `anon` and `authenticated` grants (`docs/DEPLOY.md` §1.2).
  - Its §8 lists what must be finished before 6a.
- **Phase 6a (tenancy foundation) is code complete** on branch `phase-6/tenancy-foundation`. It covers:
  - row-level security, with `outbound_app` and `outbound_platform` roles;
  - tenant-bound foreign keys;
  - workspace slug and status;
  - services per request;
  - one worker for every workspace, with a 15-minute tick.

  On Postgres the tests run as the production roles. Before deploying, set up the roles (`docs/DEPLOY.md` §1.2a).
- **Phase 6 (SaaS alpha) is planned and approved (2026-10-23):**
  - `docs/phases/phase-6-saas-ready.md` gives the overview, decisions and isolation model; the sub-phases are 6a–6g.
  - Order: 6a tenancy → 6b identity → 6c onboarding and mailboxes → 6d plans, limits and admin console → 4a opt-outs and bounces → **alpha** → 6g lead directory, in parallel with the rest of Phase 4.
  - After the alpha: 6e billing, 6f launch readiness.
- **Phase 3 (API and web app):** code complete. FastAPI (`outbound/api/`), a worker (`outbound/worker.py`), and the React app in `web2/` (served by `outbound serve` from `web2/dist`). Browser test: `cd web2 && npm run build && npx playwright test`. See `docs/phases/phase-3-api-and-web-app.md`, "How to run it".
- **New code** lives in `outbound/`, with scripts in `scripts/` and tests in `tests/`:
  - `domain/`: enums, state machines, policies, entities, ranking, copy linter, footer, edit distance. No I/O.
  - `db/`: models, the frozen migration, repositories (including reports) and the unit of work.
  - `providers/`: ports, a shared HTTP client, adapters (finders, verifiers, resolvers, Tavily, LLM, Companies House, IMAP), the registry, and `pricing.py`.
  - `metering/`: the meter (`metered.py`, `budget.py`): cache, budget guard, call, ledger row. Sits between `db`/`providers` and `stages`.
  - `stages/`: research (LangGraph), gate, contacts, email (waterfall, catch-all poller), copy (LangGraph), deliver, Sent sync.
  - `runner/`: the status runner, guards and the tick. `pipeline.py` assembles everything with metered providers.
  - `services/`: intake, review, reports, forget, seed, legacy import. `prompts/`: every model instruction.
  - `api/`: FastAPI app, auth, routers, schemas. `cli/`: `db`, `seed`, `targets`, `run`, `tick`, `retry`, `status`, `review`, `report`, `serve`, `worker`, `auth`, `import-legacy-xlsx`.
  - `web2/`: modernized React app implementing Google Stitch design system tokens (`docs/design.md`) and complete screen suite (Dashboard Variant 2, Review, Attention, Leads, LeadDetail, LeadJourney, Targets, Runs, Reports, Campaigns, Mailboxes, Compliance, Settings). Verify with `npm --prefix web2 run build`. Develop with `cd web2 && npm run dev` (port 5174, proxies `/api` to `:8000`; set `API_TARGET=http://127.0.0.1:8765` to use the fake-vendor server from `uv run python -m scripts.e2e_server`). Shared components live in `web2/src/components/ui.tsx`; status words and colours in `web2/src/lib/status.ts`.
- **Deployment:** `Dockerfile` (one image), `deploy/compose.yml` (`migrate`, `api`, `worker`; project `outbound`), `deploy/remote-deploy.sh` (build on the VM, health check, rollback), `deploy/local-test.sh` (the same deploy rehearsed locally, with a local Postgres and https proxy) and `.github/workflows/deploy.yml` (manual: host, username, ref). Secrets come from Doppler via `doppler run`; the database is Supabase Postgres (session pooler). See `docs/DEPLOY.md`.
- **`agent/`** is the legacy pipeline. Do not touch it. Its reusable parts are ported into `outbound/`, and it is deleted (with the `legacy` dependency group) after the first live run.
- **Environment:** `uv sync` builds `.venv` on Python 3.12 with the dev tools and the `legacy` dependency group. `.venv` is not tracked in git.
- **Secrets:** the root `.env` holds real vendor keys and must never be committed. `outbound/config.py` reads it through pydantic-settings (`agent/.env` is still read as a fallback but no longer exists). `test_keys.py` in the root is the operator's own key smoke test; it is untracked and excluded from linting.
- **LLM model:** DeepSeek served by DeepInfra, which replaced OpenRouter (`LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL` set to DeepInfra's OpenAI-compatible endpoint).
  - It is managed in Doppler (`outbound/dev` config) and mirrored in the root `.env`.
  - Its prices must be set in `LLM_PRICES` (3b B5).
  - From 6d, vendor keys and model settings live in the database and are managed in the admin console.
- **Provider chain** in `outbound/config.py` is **provisional** until the bake-off picks one.
- **Two facts from reading the vendors' docs:**
  - OrbiSearch has no finder API, so it can only verify.
  - Scrubby's public docs are partial, so its adapter must be confirmed with a live key.

## Architecture rules (binding)

1. **Layers:** `domain` → `db` / `providers` → `metering` → `stages` → `runner` → `services` → `pipeline` → `cli` / `api` / `worker`. Imports only point down this list. `outbound/domain` has no I/O and imports nothing from the other layers. `uv run lint-imports` checks this (CI too), and ruff bans importing `outbound.db.models` outside `outbound/db`: repositories return entities, not ORM rows.
2. **Vendor JSON never gets past an adapter.** Adapters map responses into the Pydantic models defined in `outbound/providers/ports.py`.
3. **Every paid call goes through the meter** (`outbound/metering/metered.py`: cache, then budget guard, then call, then a `provider_calls` row committed in its own transaction). Stages receive `Metered*` wrappers from `outbound/pipeline.py`; never call a vendor directly from a stage.
4. **Status changes only through the state machines** in `outbound/domain/state_machines.py`. Every transition writes an `events` row in the same transaction.
5. **No database transaction stays open across a network call.** A stage reads what it needs, does the network work, and returns a `StageResult`; the runner makes one short write that checks `row_version`.
6. **Every query on a tenant table is scoped by `workspace_id`.** No exceptions, including in scripts.
   - From 6a, Postgres row-level security enforces it as well: the app connects as `outbound_app`, never as the table owner.
   - Platform tables are reached only through their own repositories. They are users, sessions, plans and settings, vendor keys, the lead directory and the audit log.
   - Reads across workspaces go through `PlatformUnitOfWork` (`outbound/db/platform.py`), which stages, the runner, metering and tenant services may not import.
7. **Operator input wins.** The engine never overwrites a field listed in `manual_fields`; it records its own value as an event instead.
8. **Safety gates are server-side.** Suppression, country policy and safe-to-send are checked again right before every draft or send.
9. **LangGraph only inside Stage 2 (Research) and Stage 6 (Copy)**, as stateless subgraphs with no checkpointer. The outer flow is the plain Python runner, which routes on company status.
10. **The schema only changes through Alembic,** and the same PR updates `docs/SCHEMA.md`. `CHECK` value lists must equal the matching enums in `outbound/domain/enums.py`.
11. **Every API route declares its permission** with `require(Permission.X)` from Phase 6b on (`outbound/domain/permissions.py`). A test fails any tenant route that does not.

## Code standards

- Python 3.12, managed with `uv`. Type every public function. `ruff` handles both lint and format; `mypy` runs strict on `outbound/domain`.
- Design patterns are listed in `docs/PLAN.md` §5: ports and adapters, chain of responsibility for the waterfall, the `Metered` decorator, repository plus unit of work, state machine, policy objects, and constructor injection wired in `outbound/bootstrap.py`.
- Value conventions:
  - IDs are UUIDv7 strings.
  - Times are UTC.
  - Money is integer micro-USD.
  - Closed value sets are `StrEnum`s in code and `TEXT` columns with a `CHECK` constraint in SQL.
- Logging is structlog, configured once in `outbound/logging.py` (JSON on stderr, readable on a terminal; library logs from uvicorn, SQLAlchemy and httpx come out in the same shape). Log an *event name* plus the values that explain it (`log.info("run_finished", status=..., duration_ms=..., cost_micro_usd=...)`), never a sentence with the values glued in and never a bare "failed". Context (`request_id`, `run_id`, `workspace_id`, `company_id`, `stage`) is bound once and rides on every line. Levels: DEBUG for noise and cache hits, INFO for things that happened, WARNING for things that need attention (4xx, retries, a draft that could not be deleted), ERROR for bugs, always with `log.exception` inside an `except`. The redaction processor strips secrets, email text and email addresses, but do not rely on it: do not pass them in. Never log a person's name or address; log their ids.
- Errors use typed exceptions (`ProviderError`, `BudgetExceeded`, `IllegalTransition`, `ConcurrencyConflict`). Retry with tenacity only on network errors, 429 (honouring `Retry-After`, capped at a minute), 5xx, and a 202 "still processing" from a verifier; never on other 4xx. All of this is in the shared `HttpClient`, so adapters do not retry. Every HTTP call has a timeout.
- **Do not over-engineer.** The following are out unless a phase document explicitly calls for them:
  - Celery, Redis, or any queue (the companies table is the queue);
  - an event bus or CQRS;
  - microservices or a plugin framework;
  - generic base-repository hierarchies;
  - speculative abstractions.

## Testing

- No test calls the network. Use fakes for ports and recorded responses for adapters.
- Database tests run on SQLite by default, and on Postgres when `TEST_DATABASE_URL` is set (CI does this).
- Each phase document lists the tests that must exist before its gate is checked.
- Commands (from the repo root):
  - `uv sync` to build the environment.
  - `uv run pytest` runs the new suite and the legacy `agent/` suite together.
  - `uv run ruff check . && uv run ruff format --check .`
  - `uv run mypy` (checks `outbound`, `tests` and `scripts`).
  - `uv run lint-imports` checks the layer contracts.
  - Security: ruff's `S` rules run with the lint. `gitleaks` runs as a pre-commit hook (`uv run pre-commit install`) and in CI over the whole history; CI also runs `pip-audit` and `npm audit`, and Dependabot proposes updates weekly. `.gitleaks.toml` holds the one allowlisted placeholder file. Never add a `# nosec`/`noqa: S` without a reason in the comment.
  - `uv run outbound db upgrade` builds the database; `uv run outbound seed` adds the defaults.
  - `uv run --with pgserver python -m scripts.pg_tests tests -q` runs the suite on a throwaway Postgres, with no Docker.
  - Web: `cd web2 && npm run typecheck && npm run build`; `npm run gen:api` after any API change (CI fails on a stale client); `npx playwright test` runs the browser tests and the tour check against `scripts/e2e_server.py` (real app and worker, fake vendors), which serves `web2/dist`.
- Adapter tests use fixtures built from vendor documentation, not live recordings; see `tests/providers/fixtures/README.md`.
- Shared fakes live in `tests/stages/fakes.py` (vendors one by one) and `tests/stages/world.py` (a whole fake outside world for end-to-end and browser tests).
- Tests clear provider environment variables automatically, so an exported key never changes a result.

## Working conventions

- One branch per task, named `phase-N/<task>`. Keep PRs small.
- Never commit `.env` files, `data/private/`, `*.db`, or the bake-off contact list.
- **The product tour is part of the UI.** A PR that adds or changes a screen, a button or a flow in `web2/` updates `web2/src/tour/steps.ts` (add or edit the section or step, and mark the element with `data-tour="name"`, or `tour="name"` on a `Card` or `Tabs`) and the "Guided tour" part of `docs/USER_MANUAL.md`. `web2/e2e/tour.spec.ts` fails when a step points at a missing element.
- Close a phase by filling in its **Gate record** and updating the status table in `docs/phases/README.md`.
