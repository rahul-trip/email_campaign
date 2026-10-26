---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Doppler

Doppler holds the production secrets and injects them into each container when it starts, so the shared VM holds only one read-only token ([ADR 0016](../adr/0016-doppler-for-secrets.md)).

## What it holds

| Config | Used by | Holds |
|---|---|---|
| `outbound/prd` | The VM (`deploy/compose.yml`) | Every secret from `.env.example` that production uses, plus `POSTGRES_URL` (Supabase), `OPERATOR_PASSWORD_HASH`, `SESSION_SECRET`, and `INTAKE_WEBHOOK_SECRET` if the webhook is used |
| `outbound/dev` | The local deploy rehearsal (`deploy/local-test.sh`) | The same keys, with `POSTGRES_URL` pointing at the local Postgres container and its own `SESSION_SECRET`. **It holds real vendor and mailbox keys, so runs started in the rehearsal cost money and save real drafts** |

The deployment-fixed values (`DATABASE_BACKEND`, `ENVIRONMENT`, `LOG_FORMAT`, `API_HOST`, `API_PORT`, `COOKIE_SECURE`, `FORWARDED_ALLOW_IPS`) are set in `deploy/compose.yml`. They **must not** be added to Doppler. `doppler run` (without `--preserve-env`) lets a Doppler value replace a variable already in the environment, so a value added there would silently override compose. [DEPLOY.md](../../DEPLOY.md) §1.3 gives the right instruction with the wrong reason ([R-11](../tech-debt-and-risks.md#r-11--p2--configuration-doppler-overrides-compose-not-the-other-way-round)).

## How it is wired

- **The CLI.** The image installs the Doppler CLI from Doppler's signed apt repository (channel `any-version`, [R-16](../tech-debt-and-risks.md#r-16--p2--supply-chain-gaps-in-update-and-pinning-coverage)). Every container's entrypoint is `doppler run --fallback /doppler/<service>.json -- outbound …`.
- **The token.** The VM holds only a **read-only service token** for `outbound/prd` (`DOPPLER_TOKEN`), in `/opt/outbound/doppler.env`, mode 600. The deploy workflow writes it on every deploy from the GitHub `production` environment's secret, over SSH stdin.
- **Offline starts.** Each service keeps an encrypted fallback copy of its secrets on the `doppler` Docker volume, so a restart works while Doppler is unreachable.
- **Never a personal token** (`dp.pt.…`) on the VM: it can read and change every project you can.

## When it fails

| Failure | Effect | Runbook |
|---|---|---|
| Doppler unreachable at start | Containers start from the fallback file (the last secrets seen) | [doppler-token-or-outage](../operations/runbooks/doppler-token-or-outage.md) |
| Token wrong or revoked | `Doppler Error: … token` in the logs; with no fallback, containers fail | Same |
| A secret missing in `prd` | The worker exits `not configured: …` and restarts in a loop | [worker-crash-loop](../operations/runbooks/worker-crash-loop.md) |

Rotation of each secret is in [secrets management](../security/secrets-management.md).
