---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Environments

Where Outbound runs, and how each place differs. All of them run the same code. Only the database, the secrets, the proxy and the vendors change.

| | Tests | Development | Development on Postgres | Browser tests | Deploy rehearsal | Production |
|---|---|---|---|---|---|---|
| **Start** | `uv run pytest` | `uv run outbound serve` + `uv run outbound worker` | same, with `DATABASE_BACKEND=postgres` | `npx playwright test` (starts `scripts/e2e_server.py`) | `deploy/local-test.sh up` | the deploy workflow |
| **Database** | Temp SQLite file, or Postgres with `TEST_DATABASE_URL` (CI: Postgres 16 service; local: `scripts.pg_tests` with `pgserver`) | SQLite file `SQLITE_PATH` (`outbound.db`) | `POSTGRES_URL`: **use a second Supabase project, not production** | Throwaway SQLite | Local `postgres:16` container (kept between runs; `reset` deletes it) | Supabase (session pooler) |
| **Secrets** | None: provider variables cleared, `.env` ignored | `.env` | `.env` | Fixed test values | Doppler `outbound/dev` (a token in `.deploy-local/doppler.env`) | Doppler `outbound/prd` |
| **Vendors** | Fakes (`tests/stages/fakes.py`, `world.py`); recorded fixtures; network blocked | **Real (costs money)** | **Real** | Fakes (`World().providers()`) | **Real: the `dev` config holds real keys; runs cost money and save real drafts** | Real |
| **Web app** | — | `web2/dist` served by the API on `:8000`, or `npm run dev` on `:5174` | same | `web2/dist` on `:8765` | Caddy `https://localhost:8443` (its own certificate) | The VM's nginx or Caddy (TLS) |
| **Cookie `Secure`** | — | off (loopback) | off | off | on | on |
| **Logs** | captured | console on a terminal | console | console | JSON | JSON |
| **App folder** | — | the repo | the repo | the repo | `.deploy-local/` (git-ignored) | `/opt/outbound` |

## Rules

- **Production data stays in production.** Switching a laptop to `DATABASE_BACKEND=postgres` with the production `POSTGRES_URL` works on live data. Use a separate Supabase project for testing ([deployment §5.1](deployment.md#51-the-app-against-either-database)).
- **No test reaches the network or a real vendor.** pytest runs with `--disable-socket`, and `tests/test_hygiene.py` checks it.
- **The rehearsal is real, apart from the database and the proxy.** Before a rehearsal, remove the vendor and mailbox keys from Doppler `dev`, or do not start runs.
- **Data does not move between environments automatically.** A new environment starts from `outbound db upgrade` and `outbound seed`. The legacy workbook can be imported once with `outbound import-legacy-xlsx`.

## Fake-vendor server

`uv run python -m scripts.e2e_server` runs the real API and a real worker on a throwaway SQLite database, with the fake world from `tests/stages/world.py`, serving `web2/dist` on `127.0.0.1:8765` (password `e2e-password-123`). Point `npm run dev` at it with `API_TARGET=http://127.0.0.1:8765` to develop screens without spending anything.

## How to refresh this page

```bash
grep -n "image:\|ports:\|DATABASE_BACKEND\|COOKIE_SECURE" deploy/compose*.yml
sed -n '1,40p' deploy/local-test.sh
grep -n "TEST_DATABASE_URL\|disable-socket" tests/db/conftest.py pyproject.toml
```
