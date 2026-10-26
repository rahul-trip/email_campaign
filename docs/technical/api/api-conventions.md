---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# API conventions

The rules every endpoint follows. The words MUST, SHOULD and MAY are used as in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119). The endpoints are listed in the [API reference](api-reference.md), and the implementation is in the [API LLD](../lld/api.md).

## Scope and clients

- **Base path:** `/api`. The API is served from the same origin as the web app.
- **One client:** the web app, generated from the API's own OpenAPI document in the same repository. The one external caller is the [intake webhook](webhook-integration.md).
- **Format:** JSON in and out (`application/json`), except the upload (`multipart/form-data`) and errors (`application/problem+json`).
- **Time:** UTC, ISO 8601 with offset.
- **Money:** integer micro-USD (`*_micro_usd`; 1,000,000 = $1).
- **Ids:** UUIDv7 strings.

## Versioning

There is no URL or header versioning. The API and its only client ship together from one commit and one image, and the client is regenerated from the server on every API change. CI fails if `web2/openapi.json` or `web2/src/api/schema.ts` is stale (`npm run gen:api`, then `git diff --exit-code`). A change that would break an external caller (today, only the webhook) MUST be additive, or announced to its users. The app reports version `0.3.0`, which is not tied to releases ([R-19](../tech-debt-and-risks.md#r-19--p3--housekeeping-stale-references-and-inconsistent-versions)).

## Authentication

- **Login.** `POST /api/auth/login {password}` checks the operator password (Argon2) and sets the session cookie:

  | Cookie | Value |
  |---|---|
  | Name | `outbound_session` |
  | Content | Signed with `SESSION_SECRET` (itsdangerous) |
  | Lifetime | `SESSION_HOURS` (12) |
  | Flags | `HttpOnly`; `SameSite=Strict`; `Secure` when `COOKIE_SECURE` (always in production) |

- **Throttle.** 5 failed logins per 60 seconds per client address, after which the answer is `429 too_many_attempts`.
- **Every operation except** `/api/health`, `/api/auth/login` and the webhook MUST have a valid session, else `401 unauthenticated`.
- **Logout** deletes the cookie. Sessions are stateless, so a copied cookie stays valid until it expires; rotating `SESSION_SECRET` ends every session ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)).
- **The webhook** authenticates by HMAC signature instead ([webhook integration](webhook-integration.md)).

## Cross-site request forgery

Every request with a method other than GET, HEAD or OPTIONS MUST carry an `X-Requested-With` header, with any value (the web app sends `outbound`). Otherwise the answer is `403 missing_header`. A cross-site form or image cannot set a custom header. `SameSite=Strict` on the cookie is a second layer.

## Cross-origin requests

None are allowed. There is no CORS middleware, so browsers apply the same-origin policy.

## Security headers

Every response carries:

- `Content-Security-Policy: default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`.

`/api/*` responses also carry `Cache-Control: no-store`. A 500 response currently lacks these headers ([R-17](../tech-debt-and-risks.md#r-17--p3--api-a-500-response-lacks-the-security-headers)). There is no HSTS header; set it at the proxy ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)).

## Errors

Every error is a problem-details object ([RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)), with `Content-Type: application/problem+json`:

```json
{ "type": "urn:outbound:version_conflict", "title": "version_conflict", "status": 409,
  "detail": "It changed since you loaded it. Reload and try again.", "code": "version_conflict" }
```

- **Clients MUST branch on `code`.** It is stable. `detail` is a human sentence and may change.
- **`title` repeats the code** rather than giving a human title.
- **Validation errors** add `errors: [{field, message}]`.
- **A 500** never contains internal detail. Its `detail` gives a reference (the request id), which is also in the `X-Request-ID` header and in the server log.

| Status | `code` | When |
|---|---|---|
| 401 | `unauthenticated` | No valid session |
| 401 | `bad_credentials` | Wrong password |
| 401 | `bad_signature` | Webhook signature missing, malformed or wrong |
| 401 | `stale_timestamp` | Webhook timestamp more than 300 s from the server's clock |
| 403 | `missing_header` | A write without `X-Requested-With` |
| 404 | `not_found` | No such record **in this workspace** (another workspace's id is indistinguishable from a missing one) |
| 404 | `no_such_endpoint` | An `/api/...` path the server does not have, with a hint to restart `serve` and the worker after an upgrade |
| 409 | `version_conflict` | The record changed since it was read (`row_version`) |
| 409 | `action_not_allowed` | The request is valid, but the record's state does not allow it (`LeadError`, `ReviewError`, `IllegalTransition`); `detail` says why and what to do |
| 413 | `body_too_large` | Webhook body over 1,000,000 bytes |
| 422 | `validation_failed` | The body or query does not match the model (`errors` lists the fields) |
| 422 | `invalid_request` | Valid shape but unacceptable value (`InvalidInput`, `SettingsError`), e.g. an upload over 2 MB, a wrong confirmation domain |
| 422 | `bad_json` | Webhook body not a JSON object |
| 422 | `missing_event_id` | Webhook without `event_id` |
| 422 | `bad_targets` | Webhook with 0 or more than 200 targets |
| 429 | `too_many_attempts` | Login throttled |
| 500 | `internal_error` | A bug; see the reference |
| 503 | `webhook_disabled` | `INTAKE_WEBHOOK_SECRET` not set |

## Validation

- Request models (`outbound/api/schemas.py::In`) refuse unknown fields (`extra="forbid"`) and strings over 10,000 characters. Many fields have tighter limits; see the reference.
- Enumerated values (statuses, stages, rules, consent bases) are validated against the domain enums.

## Optimistic concurrency

Edits to a lead (`PATCH /api/companies/{id}`) MUST send the `row_version` the client read. Approvals SHOULD send the message's `row_version`. A stale version is refused with `409 version_conflict`; the client SHOULD reload and show the current state rather than retry blindly. The web app does this with `isConflict()`.

## Pagination

`GET /api/companies` takes `limit` (1–200, default 50) and `offset`, and returns `CompanyPage` with the items and the total. Other lists are bounded by the server: the 20 most recent runs, the review queue, and so on.

## Idempotency

| Operation | Mechanism |
|---|---|
| Webhook | `event_id`: a repeat is answered `{"duplicate": true}` and creates nothing, even when two copies race |
| Intake | Targets deduplicate by registrable domain; a repeat merges |
| Approve, reject, retry, release | State-checked: a second call finds the record already moved and answers `409 action_not_allowed` |
| Start a run | **Not idempotent:** each `POST /api/runs` queues a new run |

## Long operations

The API never runs the pipeline inside a request. `POST /api/runs` answers `202 Accepted` with the queued run, and the client polls `GET /api/runs/{id}`. Intake searches and file parsing run in a worker thread, so a slow search does not block other requests, but the request itself waits for the result.

## Request ids and logs

- A caller MAY send `X-Request-ID`. It is kept if it matches `^[A-Za-z0-9._-]{8,64}$`, and otherwise replaced.
- Every response returns the id actually used.
- The server logs one `http_request` line per request, with the route template and never the query string.

## Limits

| Limit | Value |
|---|---|
| Webhook body | 1,000,000 bytes; 1–200 targets |
| Upload | 2 MB (CSV or XLSX) |
| Strings in request models | 10,000 characters unless lower |
| Run `limit` / `discover` | 1–500 / 1–50 |
| Login | 5 failures per 60 s per client address |

## The OpenAPI document

`GET /api/openapi.json` requires a login. FastAPI's built-in docs pages are switched off, because they would load scripts from a CDN that the CSP forbids. The document is generated without a database by `uv run python -m scripts.export_openapi`. It has gaps ([R-18](../tech-debt-and-risks.md#r-18--p3--api-the-openapi-document-is-incomplete)):

- no `securitySchemes`, so the cookie, the CSRF header and the HMAC signature are not described;
- no error responses;
- eight untyped responses.

## How to refresh this page

```bash
grep -rhn "ApiError(\|WebhookError(\|problem(" outbound/api outbound/services/webhook.py | grep -o '"[a-z_]*"' | sort -u
grep -n "MAX_\|TOLERANCE\|str_max_length\|extra=" outbound/api/*.py outbound/api/routers/*.py outbound/services/webhook.py
```
