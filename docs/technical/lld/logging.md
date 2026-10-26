---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Logging

**Code:** `outbound/logging.py`, `outbound/api/request_log.py` · **Layer:** outside the layers (used by all) · **Tests:** `tests/test_logging.py`, `tests/api/test_request_logging.py`

## Purpose

One logging setup for the whole application. Every line is one structured record:

- JSON on stderr in a container;
- a readable line on a terminal.

That applies whether the line came from our code or from uvicorn, SQLAlchemy or httpx, so a log collector needs one parser. A redaction processor runs on every record, so secrets, email text and addresses do not reach the logs even by mistake. The rule is still not to pass them in ([CLAUDE.md](../../../CLAUDE.md), "Logging").

## Responsibilities

- Configure structlog and the standard `logging` module once per process.
- Add `timestamp` (UTC, ISO 8601), `level`, `logger`, `event`, `service`, `version` and `environment` to every line.
- Carry bound context (`request_id`, `client_ip`, `run_id`, `workspace_id`, `company_id`, `stage`) on every line until it is unbound.
- Redact.
- Quieten noisy libraries.
- One line per HTTP request with a request id.

**Not its job:**

- the catalogue of event names ([observability](../operations/observability.md));
- the `events` table, which is data, not logs.

## Public interface

| Symbol | Kind | What it does |
|---|---|---|
| `outbound/logging.py::configure_logging` | function | `(level, fmt, environment)`. Safe to call more than once. Called by `outbound/cli/common.py::settings_for`, so by every CLI command, `serve` and `worker` |
| `outbound/logging.py::get_logger` | function | A structlog `BoundLogger`. Use `get_logger(__name__)` |
| `outbound/logging.py::bind`, `unbind` | functions | structlog `contextvars` binding |
| `outbound/logging.py::redact` | processor | The redaction step |
| `outbound/logging.py::normalise_level` | function | Validates `LOG_LEVEL` |
| `outbound/api/request_log.py::log_requests` | middleware | Request id and the `http_request` line |

## How it works

**Format.** `LOG_FORMAT=json`, `console` or `auto`. `auto` means console when stderr is a terminal, JSON otherwise, which is what a container sees; production compose sets `json`.

**Pipeline.** Every record, from structlog or from the standard library, passes the same shared processors:

1. merge context variables;
2. add the logger name and level;
3. add an ISO UTC timestamp;
4. render stack info;
5. add the service fields.

Then a `ProcessorFormatter` runs these, in order:

1. remove internal metadata;
2. structured tracebacks (JSON) or formatted ones (console);
3. **redact**;
4. reorder so that `timestamp`, `level`, `logger` and `event` come first;
5. render.

**Context.**

| Bound by | Fields | For |
|---|---|---|
| `log_requests` | `request_id`, `client_ip` | One HTTP request |
| `Runner.run_pipeline` | `run_id`, `workspace_id` | One run |
| `Runner._process` | `company_id`, `stage` | One lead in one stage |

**Quiet libraries.** `httpx`, `httpcore`, `urllib3`, `asyncio`, `sqlalchemy.engine`, `alembic`, `multipart`, `langchain_core`, `langgraph` and `watchfiles` are raised to WARNING, or to the configured level if that is higher. Some of them would print full URLs, and several vendors put the API key in the query string. `uvicorn.access` is switched off, because the request middleware logs instead and never prints the query string.

### Redaction

| Rule | Example |
|---|---|
| A field whose name contains `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `authorization`, `cookie`, `credential` or `session` becomes `[redacted]`. Names ending in `tokens` (token counts) are exempt | `api_key="sk-…"` → `[redacted]` |
| `body`, `email_body`, `generated_body`, `final_body` and `edited_body` become `[N characters]` | — |
| An email address inside any string, including exception messages and tracebacks, keeps its first character and domain | `jane@example.com` → `j***@example.com` |
| `key=`, `api_key=`, `token=`, `access_token=`, `secret=`, `password=`, `passwd=` followed by a value, in any string | `?api_key=abc` → `?api_key=[redacted]` |
| `Bearer …` or `Basic …` with 8 or more characters | → `Bearer [redacted]` |

Nested dicts and lists are cleaned to a depth of 8.

**Not redacted:** IP addresses ([R-14](../tech-debt-and-risks.md#r-14--p2--privacy-personal-data-in-logs)), person names, domains, phone numbers. Names must never be passed in. The engine logs ids instead.

**Over-redaction:** `login_succeeded` passes `session_hours`, which matches `session` and is printed as `[redacted]`. This is harmless, but the field is useless.

### Request log

`log_requests`:

- keeps a caller's `X-Request-ID` only if it matches `^[A-Za-z0-9._-]{8,64}$`, else generates one, and echoes it in the response;
- logs `http_request` with method, route template (raw path, at most 200 characters, if no route matched), status and duration;
- uses DEBUG for successful requests to `/api/health`, `/api/status` and `/assets/…` (polled every few seconds), ERROR for 5xx, WARNING for 4xx, and INFO otherwise.

An unhandled error is also logged as `unhandled_error` with the traceback, and the client gets the request id as a reference ([API](api.md#errors)).

## Invariants

- Every line is one record with the standard fields.
- No configured secret, email body or full address reaches stderr through a field or a message.
- No URL query string is logged.

## Configuration

`LOG_LEVEL` (default INFO), `LOG_FORMAT` (`auto`), `ENVIRONMENT` (`development`; production compose sets `production`). See the [configuration reference](../operations/configuration-reference.md).

## Security and privacy

- **Logs are the operator's personal-data surface.** Client IPs are personal data and are logged unmasked ([R-14](../tech-debt-and-risks.md#r-14--p2--privacy-personal-data-in-logs)).
- **The `version` field is wrong.** It is the package version (`0.0.1`), not the deployed commit, so a log line cannot be tied to a release ([R-19](../tech-debt-and-risks.md#r-19--p3--housekeeping-stale-references-and-inconsistent-versions)).
- **Retention** is Docker's json-file rotation: 10 MB × 5 files per container.

## Tests

| File | Proves |
|---|---|
| `tests/test_logging.py` | JSON shape and bound context; library logs in the same shape; HTTP client noise silenced; level filtering; secret-named fields and bodies never written; addresses and keys masked in text; exceptions structured and masked; console mode; bad levels refused |
| `tests/api/test_request_logging.py` | Request ids kept or replaced; levels by status; quiet paths; no query strings |

## Known limitations

- There is no log shipping or alerting: logs stay in Docker on the VM ([observability](../operations/observability.md)).
- IP addresses are not masked; `session_hours` is over-redacted.

## Planned

None in the phase documents.

## How to refresh this page

```bash
grep -n "SENSITIVE_KEY_PARTS\|BODY_KEYS\|_QUIET" -A12 outbound/logging.py | head -40
grep -n "_ACCEPTABLE\|_QUIET_PREFIXES" outbound/api/request_log.py
uv run pytest tests/test_logging.py tests/api/test_request_logging.py -q
```
