# Outbound Engine

This is an outbound B2B email engine. It takes target companies, from an operator or from search, and for each one it:

1. researches the company;
2. finds and verifies a decision-maker's email;
3. writes a short personalised email;
4. once a human approves it, places it as a draft in the mailbox.

It is built for 5–50 new prospects a week at no more than $0.50 each.

**Status (2026-10-18):** Phases 0–3 are code complete and tested with fake vendors. The next step is the first live run; see [docs/phases/README.md](docs/phases/README.md).

## Documentation

- [docs/USER_MANUAL.md](docs/USER_MANUAL.md) — how to operate the application day to day (through Phase 3).
- [docs/PLAN.md](docs/PLAN.md) — the approved end-to-end plan: decisions, architecture, stages, compliance, providers.
- [docs/SCHEMA.md](docs/SCHEMA.md) — schema v1: every table, constraint, relationship and value convention.
- [docs/phases/](docs/phases/README.md) — the delivery phases, each with its tasks, gate, and what was built.
- [CLAUDE.md](CLAUDE.md) — the rules every code change follows.

## Repository layout

| Path | What it is |
|---|---|
| `outbound/` | The engine: domain core, database layer, providers and the meter, stages, runner, services, CLI and API |
| `web2/` | The React web app. FastAPI serves its build |
| `scripts/` | The Phase 0 vendor bake-off, the OpenAPI export, a throwaway Postgres for tests, and the browser-test server |
| `tests/` | Tests for `outbound/` and `scripts/`, all without network |
| `agent/` | The legacy pipeline. It is deleted after the first live run; see [agent/README.md](agent/README.md) |
| `docs/` | Plan, schema, phases, and the archive of superseded notes |
| `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` | The 10 hand-written leads, imported once and kept read-only |

## First run

### 1. Configure

Copy `.env.example` to `.env` and fill it in. `.env` is git-ignored; never commit it.

| Needed for | Variables |
|---|---|
| Research and search | `TAVILY_API_KEY` |
| Writing (research summaries, fit, copy) | `LLM_PROVIDER`, `LLM_MODEL` and that provider's key, for example `ANTHROPIC_API_KEY`. Optional: `LLM_COPY_MODEL` (a stronger model for the email only), `LLM_REASONING_EFFORT`, `LLM_MAX_TOKENS` |
| Email finding and verification | The keys for every name in `FINDER_CHAIN` and `VERIFIER` |
| Catch-all resolution (optional) | `CATCH_ALL_RESOLVER` and its key; without one, catch-all addresses are held |
| UK legal-entity check (optional, free) | `COMPANIES_HOUSE_API_KEY` |
| Drafts and the Sent sync | `IMAP_HOST`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `FROM_NAME`, `DRAFTS_FOLDER`, `SENT_FOLDER` |
| The web app | `OPERATOR_PASSWORD_HASH` (from `uv run outbound auth hash-password`) and `SESSION_SECRET` |
| Spend limits (optional) | `MONTHLY_CAPS_MICRO_USD`, `PROVIDER_PRICES`, `LLM_PRICES` |

### 2. Create the database

```bash
uv sync
uv run outbound db upgrade
uv run outbound seed                     # default workspace, campaign and country policies
```

Then fill in the **sender profile** (legal name, postal address, registration details, signature) and the **campaign** (wanted job titles, ideal customer, research questions). Do it in the web app under Settings. The engine will not write an email until the footer fields are filled.

### 3. Run it

**In the browser**

```bash
(cd web2 && npm ci && npm run build)     # once, and after UI changes
uv run outbound serve                    # http://127.0.0.1:8000
uv run outbound worker                   # second terminal: executes the runs you start
```

Add targets, start a run, review and approve in the Review screen, and run again to draft. Drafts appear in your mailbox's Drafts folder; send them from your mail client.

**From the command line**

```bash
uv run outbound targets import targets.csv --validate-only   # check a file first
uv run outbound targets import targets.csv
uv run outbound run                                          # every stage over the work that is due
uv run outbound review list
uv run outbound review approve MESSAGE_ID [--edit FILE]
uv run outbound run                                          # drafts what you approved
uv run outbound tick                                         # retries, catch-all answers, Sent sync
uv run outbound status
uv run outbound report quality
uv run outbound report cost --days 30
```

`outbound worker` runs a tick for every workspace every 15 minutes by itself (`--tick-minutes`), so no cron job is needed while it runs. Without the worker, run `outbound tick` from cron or a launchd timer.

## Development

```bash
uv run pytest                            # Python tests (new and legacy)
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run --with pgserver python -m scripts.pg_tests tests -q   # the same suite on a throwaway Postgres
uv run datasette outbound.db --immutable                     # read-only database viewer

cd web2
npm run typecheck && npm run build
npm run gen:api                          # regenerate the client after any API change
npx playwright test                      # browser tests (and the guided tour), against fake vendors
npm run dev                              # live-reloading app on :5174; API_TARGET=http://127.0.0.1:8765
                                         # points it at `uv run python -m scripts.e2e_server`

```
