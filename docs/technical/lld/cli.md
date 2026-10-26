---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# CLI

**Code:** `outbound/cli/` (`main.py`, `common.py`, `ops.py`, `serve.py`, `targets.py`, `profile.py`, `privacy.py`) · **Layer:** entry point · **Tests:** `tests/test_cli.py`

## Purpose

`outbound` is the command-line door to the same use cases as the web app. It also provides the process entry points (`serve`, `worker`, `tick`) and the database commands. It exists so that everything can be done and automated from a terminal, and so that the containers have one entry point.

## Responsibilities

- Parse arguments (Typer) and print readable results.
- Build the container from settings, pick the workspace, call one service, and exit with a clear message.
- Start the API (`serve`) and the worker (`worker`); run one scheduler pass (`tick`).

**Not its job:** business rules ([services](services.md)). The CLI calls the same services as the API, so the same refusals apply.

## Commands

The entry points are `outbound = "outbound.cli.main:app"` (`pyproject.toml`) and `python -m outbound`. Every command that touches data also takes `--database-url` (or the `DATABASE_URL` environment variable) and `--workspace` (default `default`).

| Command | Arguments and options | What it does | Calls |
|---|---|---|---|
| `db upgrade` | `[REVISION=head]` | Bring the schema up to date | `outbound.db.migrate.upgrade` |
| `db downgrade` | `[REVISION=-1]` | Step the schema back (**can drop data**) | `migrate.downgrade` |
| `db current` | | The current and latest revision | `migrate.current_revision` |
| `seed` | | Default workspace, campaign and country rules; safe to repeat | `seed_defaults` |
| `import-legacy-xlsx` | `PATH` | The old campaign workbook, once; idempotent | `import_legacy_xlsx` |
| `targets import` | `PATH --validate-only --campaign --allow-personal-domain` | Import a CSV or XLSX of targets | `IntakeService.run` |
| `targets add` | `--company --website --email --person --title --linkedin --country --note --priority(1–9) --validate-only --campaign --allow-personal-domain` | One target | `IntakeService.run` |
| `targets pending` | | Rows waiting for a website decision | `IntakeService.needing_confirmation` |
| `targets confirm` | `ROW_ID DOMAIN` | Choose the website for a waiting row | `IntakeService.confirm` |
| `run` | `--limit 50 --only a,b --mode manual\|discovery\|mixed --discover 10 --campaign` | Discovery (unless manual), then every stage over due work, in the foreground | `pipeline.execute_run` |
| `tick` | `--limit 50` | Retries, catch-all answers, the Sent sync, then the pipeline | `Tick.run` |
| `retry` | `--limit 50` | Send failed leads back once their wait is over | `Runner.retry_failed` |
| `status` | | Leads by status, holds and why, failures | `ReportService.status` |
| `review list` / `show REF` | | The queue; one email with what is known about the lead | `ReviewService.queue`, `show` |
| `review approve` | `REF --edit FILE --acknowledge-skips` | Approve, optionally with an edited text; skipped checks need the flag | `ReviewService.approve` |
| `review reject` | `REF --reason` | Reject and end work on the lead | `ReviewService.reject` |
| `report quality` | | Unedited share, flags, holds | `ReportService.quality` |
| `report cost` | `--days 30` | Spend per provider and per prospect | `ReportService.cost` |
| `sender-profile show` / `review --yes` | | Print the profile; confirm every statement is true (sets `reviewed_at`) | `SettingsService` |
| `forget` | `EMAIL --yes` | Erase a person | `PrivacyService.forget` |
| `delete-lead` | `DOMAIN --suppress --yes` | Delete a lead (refused once emailed) | `PrivacyService.delete_lead` |
| `suppress` | `VALUE` | Never contact an address or domain | `PrivacyService.suppress_value` |
| `auth hash-password` | (prompted twice, hidden) | Print the value for `OPERATOR_PASSWORD_HASH` | `argon2` |
| `serve` | `--host --port` | The API and web app (uvicorn) | `create_app_from_container` |
| `worker` | `--poll-seconds 2.0` | Execute queued runs until stopped | `Worker.run_forever` |

`REF` is a message id or an unambiguous prefix of one.

## How the process commands work

- **`serve`:**
  - Runs one uvicorn process with `proxy_headers=True`, `forwarded_allow_ips=FORWARDED_ALLOW_IPS`, no access log (the app logs `http_request` itself), and the app's logging configuration.
  - **Refuses to bind a non-loopback host unless `COOKIE_SECURE` is set**, so the session cookie is never sent over plain HTTP.
  - Fails at start without `OPERATOR_PASSWORD_HASH` or `SESSION_SECRET`.
  - Logs `service_started` (`role=api`, with the database URL, password hidden).
- **`worker`:**
  - Assembles the pipeline over the real providers.
  - A missing key prints `not configured: …` and exits 1.
  - Logs `service_started` (`role=worker`).
  - Stops on Ctrl-C. There is no SIGTERM handler ([R-05](../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3)).
- **`tick`:**
  - Meant for cron or a timer, every 15–30 minutes.
  - Nothing schedules it in production ([R-02](../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7)).

## Settings and the database

`outbound/cli/common.py::settings_for(database_url)` loads `Settings` and, if `--database-url` or `DATABASE_URL` is given, replaces `database_url` with it. Otherwise `DATABASE_BACKEND` picks SQLite or `POSTGRES_URL` ([configuration and bootstrap](configuration-and-bootstrap.md)). `workspace_id_or_exit` prints a clear message ("run `outbound seed`") if the database is not migrated or seeded.

## Running on the VM

Every command runs inside a one-off container with the real secrets ([deployment](../operations/deployment.md)):

```bash
cd /opt/outbound/current
export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
oc run --rm --no-deps api outbound status
oc run --rm --no-deps api outbound report cost --days 7
```

Each one-off command opens its own connection pool, which counts against the Supabase pooler limit ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)).

## Errors

Service refusals (`LeadError`, `ReviewError`, `InvalidInput`, …) print their message and exit non-zero. Missing configuration exits 1 with what is missing. Unexpected exceptions show Typer's traceback; secrets and addresses are not printed, because the CLI never echoes them.

## Configuration

The same `Settings` as the API, and the worker's `--workspace` must match the API's `WORKSPACE_NAME` ([R-22](../tech-debt-and-risks.md#r-22--p3--configuration-the-api-and-the-worker-can-bind-to-different-workspaces)).

## Observability

`service_started`, plus whatever the called code logs. Command results go to stdout, and logs to stderr (JSON when not on a terminal).

## Tests

`tests/test_cli.py` covers:

- seeded workspace required;
- `run` without credentials changes nothing and says what is missing;
- `status`, `review` and the reports on an empty database;
- unknown message references;
- the sender-profile confirmation;
- a migrated but unseeded database.

## Planned

- Phase 4 adds reply-handling commands: [phase-4-close-the-loop.md](../../phases/phase-4-close-the-loop.md).

## How to refresh this page

```bash
uv run outbound --help
uv run python - <<'EOF'
import typer
from outbound.cli.main import app
def walk(c, p):
    if hasattr(c, "commands"):
        for n, s in sorted(c.commands.items()): walk(s, p + [n])
    else:
        print("outbound", *p, [x.opts[0] if x.opts else x.name for x in c.params])
walk(typer.main.get_command(app), [])
EOF
```
