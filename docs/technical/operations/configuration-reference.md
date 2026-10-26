---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Configuration reference

Every setting the engine reads. There are two kinds:

- **Environment settings:** 52 fields of `outbound/config.py::Settings`, read at process start.
- **Workspace settings:** stored in `workspaces.settings` and edited in the app.

How settings load, their precedence and their validation are in [configuration and bootstrap](../lld/configuration-and-bootstrap.md). Secrets and their rotation are in [secrets management](../security/secrets-management.md).

**Where each value is set in production:**

- **D:** Doppler `outbound/prd`;
- **C:** fixed in `deploy/compose.yml` (must not be in Doppler, [R-11](../tech-debt-and-risks.md#r-11--p2--configuration-doppler-overrides-compose-not-the-other-way-round));
- **—:** usually left at the default.

Locally, everything comes from `.env` (template: `.env.example`).

**Secret** marks a `SecretStr`, which never prints. Values marked "(holds a password)" are plain strings that contain one.

## Database

| Variable | Type | Default | Secret | Where | Purpose |
|---|---|---|---|---|---|
| `DATABASE_BACKEND` | `sqlite` \| `postgres` | `sqlite` | | C (`postgres`) | Which database to use when `DATABASE_URL` is empty |
| `SQLITE_PATH` | str | `outbound.db` | | — | SQLite file for the `sqlite` backend |
| `POSTGRES_URL` | str | — | (holds a password) | D | Supabase session-pooler URL, with `?sslmode=require` |
| `DATABASE_URL` | str | — | (holds a password) | — | Overrides the switch (tests, `--database-url`) |
| `DATABASE_POOL_SIZE` | int | 5 | | D if needed | Connections per process; lower it for small Supabase plans ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)) |

## Logging

| Variable | Type | Default | Where | Purpose |
|---|---|---|---|---|
| `LOG_LEVEL` | DEBUG … CRITICAL | `INFO` | — | Minimum level |
| `LOG_FORMAT` | `auto` \| `json` \| `console` | `auto` | C (`json`) | `auto` is console on a terminal, JSON otherwise |
| `ENVIRONMENT` | str | `development` | C (`production`) | Printed on every log line |

## Vendors

| Variable | Type | Default | Secret | Where | Needed for |
|---|---|---|---|---|---|
| `TAVILY_API_KEY` | str | — | yes | D | Research, discovery, name-only intake (the worker refuses to start without it) |
| `HUNTER_API_KEY` | str | — | yes | D | `hunter` in the chain |
| `ZEROBOUNCE_API_KEY` | str | — | yes | D | `zerobounce` in the chain |
| `MYEMAILVERIFIER_API_KEY` | str | — | yes | D | `VERIFIER=myemailverifier` (default) |
| `ORBISEARCH_API_KEY` | str | — | yes | D | `VERIFIER=orbisearch` |
| `ENRICHLEY_API_KEY` | str | — | yes | D | `CATCH_ALL_RESOLVER=enrichley` |
| `SCRUBBY_API_KEY` | str | — | yes | D | `CATCH_ALL_RESOLVER=scrubby` (default) |
| `SCRUBBY_BASE_URL` | str | — | | D | Required with Scrubby; not documented publicly ([R-09](../tech-debt-and-risks.md#r-09--p1--vendors-the-provider-chain-is-unproven-e5-d5)) |
| `COMPANIES_HOUSE_API_KEY` | str | — | yes | D | Optional: UK incorporation checks |
| `FINDER_CHAIN` | comma list | `hunter,zerobounce` | | D | Finders, in order (provisional) |
| `VERIFIER` | str | `myemailverifier` | | D | The verifier |
| `CATCH_ALL_RESOLVER` | str | `scrubby` | | D | The resolver; with no key, catch-alls are held as unverified |

## Language model

| Variable | Type | Default | Secret | Where | Purpose |
|---|---|---|---|---|---|
| `LLM_PROVIDER` | str | `anthropic` | | D | `anthropic`, `openai`, `gemini`, `ollama`, `github_copilot`, `openai_compatible` ([llm](../integrations/llm.md)) |
| `LLM_MODEL` | str | `claude-sonnet-5-5` | | D | The model name sent to the provider |
| `LLM_BASE_URL` | str | — | | D if needed | Required for `openai_compatible`; overrides a preset's address |
| `LLM_TEMPERATURE` | float | 0.7 | | — | Sampling temperature |
| `LLM_MAX_TOKENS` | int | 4000 | | — | Reply limit; raise it if replies are cut off |
| `ANTHROPIC_API_KEY` | str | — | yes | D | Key for the `anthropic` preset |
| `OPENAI_API_KEY` | str | — | yes | D | Key for `openai` |
| `GEMINI_API_KEY` | str | — | yes | D | Key for `gemini` |
| `COPILOT_API_KEY` | str | — | yes | D | Key for `github_copilot` |
| `LLM_API_KEY` | str | — | yes | D | Key for `openai_compatible`, and the fallback for any preset |

## Mailbox (IMAP)

Without `IMAP_HOST` and `EMAIL_ADDRESS`, there is no deliver stage and no Sent sync.

| Variable | Type | Default | Secret | Where | Purpose |
|---|---|---|---|---|---|
| `IMAP_HOST` | str | — | | D | Mail server |
| `IMAP_PORT` | int | 993 | | — | Port |
| `IMAP_USE_SSL` | bool | true | | — | IMAPS |
| `EMAIL_ADDRESS` | str | — | | D | Login and sender address |
| `EMAIL_PASSWORD` | str | — | yes | D | Password (an app password if the provider offers one) |
| `FROM_NAME` | str | — | | D | Display name on drafts |
| `DRAFTS_FOLDER` | str | `INBOX.Drafts` | | D if different | Where drafts are saved |
| `SENT_FOLDER` | str | `INBOX.Sent` | | D if different | What the Sent sync reads |
| `INBOX_FOLDER` | str | `INBOX` | | — | Phase 4 |
| `IMAP_TIMEOUT_SECONDS` | float | 30 | | — | Per IMAP session |

## Spend

| Variable | Type | Default | Where | Purpose |
|---|---|---|---|---|
| `PROVIDER_PRICES` | JSON object, `"vendor:operation"` → micro-USD | `{}` | D | Overrides the built-in prices ([integrations](../integrations/README.md#prices)) |
| `LLM_PRICES` | JSON object, model → `[input, output]` micro-USD per million tokens | `{}` | **D (set it)** | Without it, every model call is recorded at $0 ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)) |
| `MONTHLY_CAPS_MICRO_USD` | JSON object, provider → micro-USD | `{}` | D | Monthly cap per provider |

Example: `LLM_PRICES={"claude-sonnet-5-5": [3000000, 15000000]}` records $3 per million input tokens and $15 per million output tokens. Use your provider's current prices.

## Web app and API

| Variable | Type | Default | Secret | Where | Purpose |
|---|---|---|---|---|---|
| `OPERATOR_PASSWORD_HASH` | str | — | (sensitive) | D | Argon2 hash from `outbound auth hash-password`; `serve` will not start without it |
| `SESSION_SECRET` | str | — | yes | D | Signs the session cookie (≥ 16 characters; use 64 hex characters) |
| `SESSION_HOURS` | int | 12 | | — | Session lifetime |
| `INTAKE_WEBHOOK_SECRET` | str | — | yes | D if used | Enables and signs the webhook |
| `COOKIE_SECURE` | bool | false | | C (`true`) | `Secure` cookie flag. `serve` refuses a non-loopback host without it |
| `API_HOST` | str | `127.0.0.1` | | C (`0.0.0.0` inside the container) | Bind address |
| `API_PORT` | int | 8000 | | C | Port inside the container (published on `127.0.0.1:$OUTBOUND_PORT`, default 8010) |
| `FORWARDED_ALLOW_IPS` | str | `127.0.0.1` | | C (`*`) | Proxies whose `X-Forwarded-For` is trusted |
| `WORKSPACE_NAME` | str | `default` | | — | The API's workspace. **Leave it at `default`**: the worker and CLI do not read it ([R-22](../tech-debt-and-risks.md#r-22--p3--configuration-the-api-and-the-worker-can-bind-to-different-workspaces)) |

**Deployment-only variables** (read by the deploy scripts, not by `Settings`):

| Variable | Where | Purpose |
|---|---|---|
| `DOPPLER_TOKEN` | `/opt/outbound/doppler.env` (written by the workflow) | Lets `doppler run` fetch the secrets |
| `OUTBOUND_PORT` | `/opt/outbound/settings.env`, or the workflow's `port` input | The VM loopback port (default 8010) |
| `RELEASE`, `OUTBOUND_HOME`, `OUTBOUND_COMPOSE_EXTRA`, `KEEP_RELEASES` | `deploy/remote-deploy.sh` | Release id, app folder, the rehearsal overlay, how many releases to keep |

## Workspace settings

These are stored in `workspaces.settings` and edited in the app (Settings, and Policies and privacy) or through `PUT /api/settings/workspace`. Every change writes a `settings_changed` event. They take effect for new decisions immediately, except the per-prospect ceiling, which a running worker reads only at start ([R-10](../tech-debt-and-risks.md#r-10--p1--budget-a-running-worker-does-not-see-budget-changes-b4)).

| Key | Default | Editable | Purpose |
|---|---|---|---|
| `safe_to_send_only` | true | yes | Refuse unverifiable catch-all addresses |
| `budget_per_prospect_micro_usd` | 500,000 ($0.50) | yes (`null` means no ceiling; `0` means no paid calls) | Per-lead spend ceiling |
| `few_shot_examples` | 5 | yes (0–20) | Operator edits shown to the writer |
| `timezone` | `UTC` | yes | For the Phase 5 send window |
| `country_policy_enabled` | true | yes | Off skips every country rule (red banner); suppression still applies |
| `footer_enabled` | true | yes | Add the legal footer to emails |
| `send_enabled` | false | **no**: refused before Phase 5 | Automatic sending |
| `breaker` | `{hard_per_100: 3, hard_per_24h: 2}` | no | Phase 5 bounce circuit breaker |
| `catch_all_resolver` | `scrubby` | no | **Unused**: the environment's `CATCH_ALL_RESOLVER` decides (Phase 3b B9) |
| `reply_webhook_url` | null | no | Phase 4 |

## How to refresh this page

```bash
uv run python -c "
from outbound.config import Settings
for n, f in Settings.model_fields.items(): print(n.upper(), f.annotation, f.default)" | wc -l      # 52
grep -n "environment:" -A12 deploy/compose.yml
sed -n '/def default_workspace_settings/,/}/p' outbound/services/defaults.py
grep -n "SETTING_FIELDS" -A10 outbound/services/settings.py
```
