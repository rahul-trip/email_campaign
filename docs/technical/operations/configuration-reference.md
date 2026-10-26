---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-27 (5f6dee4)
applies_to: Phase 6a/6b/6c
---

# Configuration reference

Every setting the engine reads. There are two kinds:

- **Environment settings:** 58 fields of `outbound/config.py::Settings`, read at process start.
- **Workspace settings:** stored in `workspaces.settings` and edited in the app.

**Removed since Phase 3b:** `OPERATOR_PASSWORD_HASH`, `SESSION_SECRET`, `SESSION_HOURS`, `WORKSPACE_NAME`, `INTAKE_WEBHOOK_SECRET`, `IMAP_HOST`, `IMAP_PORT`, `IMAP_USE_SSL`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `FROM_NAME`, `DRAFTS_FOLDER`, `SENT_FOLDER`, `INBOX_FOLDER`, `IMAP_TIMEOUT_SECONDS` — real accounts and revocable sessions replaced the single operator password ([identity and access](../lld/identity-and-access.md)), and per-workspace, database-backed mailboxes replaced the one IMAP mailbox in the environment ([mailboxes and OAuth](../lld/mailboxes-and-oauth.md)).

How settings load, their precedence and their validation are in [configuration and bootstrap](../lld/configuration-and-bootstrap.md). Secrets and their rotation are in [secrets management](../security/secrets-management.md).

**Where each value is set in production:**

- **D:** Doppler `outbound/prd`;
- **C:** fixed in `deploy/compose.yml` (must not be in Doppler, [R-11](../tech-debt-and-risks.md#r-11--p2--configuration-doppler-overrides-compose-not-the-other-way-round));
- **—:** usually left at the default.

Locally, everything comes from `.env` (template: `.env.example`).

**Secret** marks a `SecretStr`, which never prints. Values marked "(holds a password)" are plain strings that contain one.

## Database

Three roles, three URLs — see [tenancy and isolation](../lld/tenancy-and-isolation.md#three-connections) for why.

| Variable | Type | Default | Secret | Where | Purpose |
|---|---|---|---|---|---|
| `DATABASE_BACKEND` | `sqlite` \| `postgres` | `sqlite` | | C (`postgres`) | Which database to use when `DATABASE_URL` is empty |
| `SQLITE_PATH` | str | `outbound.db` | | — | SQLite file for the `sqlite` backend |
| `POSTGRES_URL` | str | — | (holds a password) | D | Supabase session-pooler URL, with `?sslmode=require`; connects as `outbound_app` |
| `POSTGRES_PLATFORM_URL` | str | — (falls back to `POSTGRES_URL`) | (holds a password) | D | The cross-workspace, read-mostly connection; connects as `outbound_platform`. Leaving it unset in production means the scheduler runs as `outbound_app` instead — see [R-26](../tech-debt-and-risks.md#r-26--p3--configuration-platform_database_url-silently-falls-back-to-database_url) |
| `POSTGRES_MIGRATE_URL` | str | — (falls back to `POSTGRES_URL`) | (holds a password) | D (migrate container only) | The owner connection; the only role Alembic may run as |
| `DATABASE_URL` | str | — | (holds a password) | — | Overrides the switch (tests, `--database-url`) |
| `PLATFORM_DATABASE_URL` | str | — (falls back to `DATABASE_URL`) | (holds a password) | — | Overrides `POSTGRES_PLATFORM_URL`'s resolution |
| `MIGRATE_DATABASE_URL` | str | — (falls back to `DATABASE_URL`) | (holds a password) | — | Overrides `POSTGRES_MIGRATE_URL`'s resolution |
| `DATABASE_POOL_SIZE` | int | 5 | | D if needed | Connections per process, per engine; lower it for small Supabase plans ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)) |

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
| `LLM_COPY_MODEL` | str | — (falls back to `LLM_MODEL`) | | D if different | A separate, usually stronger, model for the copy stage; research can stay on a cheaper model |
| `LLM_REASONING_EFFORT` | `low` \| `medium` \| `high` \| `""` | `""` | | D if used | Sent as `reasoning.effort` to a model that accepts it (e.g. via OpenRouter); counts against `LLM_MAX_TOKENS` |

## Mailboxes and OAuth

There is no single operator mailbox any more — each workspace connects its own, in Settings → Mailboxes, stored (encrypted) in the `mailboxes`/`credentials` tables. See [mailboxes and OAuth](../lld/mailboxes-and-oauth.md). These settings configure the platform's own OAuth applications and the IMAP connection guard, not any one mailbox.

| Variable | Type | Default | Secret | Where | Purpose |
|---|---|---|---|---|---|
| `MICROSOFT_CLIENT_ID` | str | — | | D | The platform's multi-tenant Entra app id; without it, "Connect Microsoft 365" is not offered |
| `MICROSOFT_CLIENT_SECRET` | str | — | yes | D | Its client secret |
| `GOOGLE_CLIENT_ID` | str | — | | D | The platform's Google Cloud OAuth client id; without it, "Connect Google Workspace" is not offered |
| `GOOGLE_CLIENT_SECRET` | str | — | yes | D | Its client secret |
| `MAILBOX_TIMEOUT_SECONDS` | float | 30 | | — | Per mailbox network call (IMAP, Graph, Gmail API) |
| `SECRETS_KEYS` | JSON, `{"<version>": "<base64 32 bytes>"}` | — | yes | D | Encrypts every workspace's mailbox credentials and the platform's vendor keys (AES-256-GCM). The highest version always encrypts; `outbound secrets new-key` generates one. Losing it makes every stored credential permanently unreadable ([R-25](../tech-debt-and-risks.md#r-25--p2--secrets-secrets_keys-is-a-single-point-of-failure-for-every-workspaces-encrypted-credentials)) |

## Spend

| Variable | Type | Default | Where | Purpose |
|---|---|---|---|---|
| `PROVIDER_PRICES` | JSON object, `"vendor:operation"` → micro-USD | `{}` | D | Overrides the built-in prices ([integrations](../integrations/README.md#prices)) |
| `LLM_PRICES` | JSON object, model → `[input, output]` micro-USD per million tokens | `{}` | **D (set it)** | Without it, every model call is recorded at $0 ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)) |
| `MONTHLY_CAPS_MICRO_USD` | JSON object, provider → micro-USD | `{}` | D | Monthly cap per provider |

Example: `LLM_PRICES={"claude-sonnet-5-5": [3000000, 15000000]}` records $3 per million input tokens and $15 per million output tokens. Use your provider's current prices.

## Identity, web app and API

Accounts, sessions and permissions replaced the single operator password in Phase 6b — see [identity and access](../lld/identity-and-access.md).

| Variable | Type | Default | Secret | Where | Purpose |
|---|---|---|---|---|---|
| `SECRETS_KEYS` | JSON | — | yes | D | Also used here indirectly: see Mailboxes and OAuth above |
| `APP_BASE_URL` | str | `http://127.0.0.1:8000` | | C/D (the real host) | The host invitation, reset and OAuth-redirect links start with |
| `SUPERADMIN_ENABLED` | bool | true | | D (`false` to disable) | Alpha-only: lets a platform superadmin read any workspace, read-only |
| `TERMS_VERSION` | str | `2026-10` | | D if changed | The Terms version a person accepts when they set a password |
| `EMAIL_FROM` | str | `Outbound <no-reply@localhost>` | | D | From-address on invitation/reset emails |
| `SMTP_HOST` | str | — (blank: log instead of send) | | D in production | The platform's own outbound mail relay for invites and resets — never a customer's mailbox |
| `SMTP_PORT` | int | 587 | | — | — |
| `SMTP_USERNAME` | str | — | | D if used | — |
| `SMTP_PASSWORD` | str | — | yes | D if used | — |
| `COOKIE_SECURE` | bool | false | | C (`true`) | `Secure` cookie flag (and the `__Host-` cookie name). `serve` refuses a non-loopback host without it |
| `API_HOST` | str | `127.0.0.1` | | C (`0.0.0.0` inside the container) | Bind address |
| `API_PORT` | int | 8000 | | C | Port inside the container (published on `127.0.0.1:$OUTBOUND_PORT`, default 8010) |
| `FORWARDED_ALLOW_IPS` | str | `127.0.0.1` | | C (`*`) | Proxies whose `X-Forwarded-For` is trusted |

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
| `directory_share_operator_contacts` | false | the key is read; no screen yet | Whether an operator-typed contact may be contributed to the [lead directory](../lld/lead-directory.md) |

A workspace's **plan, entitlements, overrides and grants** are a separate, platform-admin-managed layer on top of these settings — not stored in `workspaces.settings` at all. See [plans, credits and admin](../lld/plans-credits-and-admin.md).

## How to refresh this page

```bash
uv run python -c "
from outbound.config import Settings
for n, f in Settings.model_fields.items(): print(n.upper(), f.annotation, f.default)" | wc -l      # 58
grep -n "environment:" -A12 deploy/compose.yml
sed -n '/def default_workspace_settings/,/}/p' outbound/services/defaults.py
grep -n "SETTING_FIELDS" -A10 outbound/services/settings.py
```
