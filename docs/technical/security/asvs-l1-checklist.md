---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# OWASP ASVS level 1 checklist

A self-assessment against the [OWASP Application Security Verification Standard](https://owasp.org/www-project-application-security-verification-standard/), level 1. It is organised by the ASVS 4.0.3 chapters. Requirements are paraphrased, and those that do not apply to a single-operator, server-rendered-API app are left out. This page is evidence, not certification: each row cites where the control is, or the register entry for the gap.

**Status:** **Met**, **Partial**, **Gap**, or **N/A** with the reason.

## V1 Architecture and threat modelling

| Requirement | Status | Evidence |
|---|---|---|
| A threat model exists and is kept current | Met | [threat model](threat-model.md); reviewed at each phase gate |
| Security controls are centralised (authn, access control, validation, output encoding) | Met | `outbound/api/auth.py`; router-level dependencies in `outbound/api/app.py`; Pydantic `In` models |
| Components are separated by trust and the layering is enforced | Met | import-linter contracts ([HLD](../hld/hld.md#1-decomposition)) |

## V2 Authentication

| Requirement | Status | Evidence |
|---|---|---|
| Passwords are stored with an approved adaptive hash | Met | Argon2 (`argon2-cffi`), `outbound/api/auth.py` |
| Brute force is limited | Partial | 5 failures per 60 s per client address; in memory, per process ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)) |
| No default or shared credentials | Met | The hash is created by the operator with `outbound auth hash-password`; the app will not start without one |
| Credentials are sent only over TLS | Met | `COOKIE_SECURE` in production; `serve` refuses a network bind without it; TLS at the proxy |
| Password length and complexity, breached-password check | Gap | No policy is enforced on the operator's password; one trusted operator |
| Multi-factor authentication | N/A until Phase 6 | One operator; Supabase auth is planned |
| Password change and recovery flows | N/A | The password is replaced through configuration ([secrets](secrets-management.md)) |

## V3 Session management

| Requirement | Status | Evidence |
|---|---|---|
| Session tokens are random, signed and not in URLs | Met | itsdangerous-signed cookie; never in a URL |
| Cookies are `Secure`, `HttpOnly`, `SameSite` | Met | `routers/auth.py` (`SameSite=Strict`) |
| Sessions expire | Met | `SESSION_HOURS` (12) |
| Logout invalidates the session on the server | Gap | Stateless tokens; logout deletes the cookie only ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)) |
| A new session token is issued at login | Met | A new signed token each login |

## V4 Access control

| Requirement | Status | Evidence |
|---|---|---|
| Deny by default; every operator route requires a session | Met | `require_operator` on every router except auth, webhook, health; `tests/api/` |
| Cross-site request forgery is prevented | Met | `X-Requested-With` on writes plus `SameSite=Strict` |
| Records are scoped to the tenant | Met | `workspace_id` on every query (`ScopedRepository._row`); another workspace's id is `404` |
| Administrative interfaces are protected | Met | OpenAPI document behind login; no Swagger or ReDoc pages |

## V5 Validation, sanitisation and encoding

| Requirement | Status | Evidence |
|---|---|---|
| Input is validated by allow-list (types, ranges, lengths) | Met | Pydantic `In` models: `extra="forbid"`, strings ≤ 10,000 characters, ranged numbers, enums |
| Parameterised queries only | Met | SQLAlchemy ORM and Core throughout; ruff `S608` |
| Output is encoded for its context | Met | React renders text; no `dangerouslySetInnerHTML` in `web2/src`; strict CSP |
| Email header injection prevented | Met | The subject is normalised to one line (`outbound/stages/copy/graph.py::Snippets`); headers built with `email.message.EmailMessage` |
| Untrusted content kept out of instructions (LLM) | Partial | Fenced prompts; the fence can be closed early ([R-08](../tech-debt-and-risks.md#r-08--p1--security-web-text-can-close-the-prompt-fence)) |
| File uploads are size-limited and type-checked | Met | 2 MB; CSV or XLSX parsed by `load_rows`; never stored or served |

## V6 Stored cryptography

| Requirement | Status | Evidence |
|---|---|---|
| Approved algorithms only | Met | Argon2, HMAC-SHA256, SHA-256 |
| Secrets are not hard-coded | Met | Doppler and `.env`; gitleaks |
| Hashes of low-entropy personal data are salted or keyed | Gap | Suppression hashes are unsalted SHA-256 ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)) |

## V7 Error handling and logging

| Requirement | Status | Evidence |
|---|---|---|
| Errors do not reveal internals | Met | Generic 500 with a reference (`tests/api/test_security.py::test_a_bug_is_a_plain_500_with_no_internal_detail`) |
| Security events are logged (logins, failures, access denials) | Met | `login_succeeded`, `login_failed`, `login_throttled`, `http_request` (4xx at WARNING) |
| Logs exclude credentials, session tokens and sensitive data | Partial | Redaction processor; client IPs logged ([R-14](../tech-debt-and-risks.md#r-14--p2--privacy-personal-data-in-logs)) |
| Logs carry a time source and correlation | Met | UTC ISO timestamps; `request_id`, `run_id` |

## V8 Data protection

| Requirement | Status | Evidence |
|---|---|---|
| Sensitive responses are not cached | Met | `Cache-Control: no-store` on `/api/*` (not on 500s, [R-17](../tech-debt-and-risks.md#r-17--p3--api-a-500-response-lacks-the-security-headers)) |
| Personal data can be erased | Met | Forget; tested by scanning every column |
| Personal data can be exported to its subject | Gap | [R-23](../tech-debt-and-risks.md#r-23--p2--privacy-no-way-to-answer-a-subject-access-request) |
| Retention is defined | Gap | [R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3) |

## V9 Communication

| Requirement | Status | Evidence |
|---|---|---|
| TLS for all client connections | Met | The VM's proxy; loopback-only app port |
| TLS to back-end services | Partial | Vendors HTTPS; IMAPS; the database only with `sslmode=require` in the URL ([R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler)) |
| HSTS | Gap | Not set by the app or the example proxy configurations ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)) |

## V10 Malicious code

| Requirement | Status | Evidence |
|---|---|---|
| Dependencies are pinned and scanned | Partial | Lockfiles; pip-audit; npm audit; Dependabot misses `web2` and images ([R-16](../tech-debt-and-risks.md#r-16--p2--supply-chain-gaps-in-update-and-pinning-coverage)) |
| No secrets or back doors in the repository | Met | gitleaks over the whole history in CI |

## V11 Business logic

| Requirement | Status | Evidence |
|---|---|---|
| Business flows run in order and cannot be skipped | Met | State machines; server-side safety gates; approval before drafting ([safety model](../hld/safety-model.md)) |
| Limits on high-value operations | Partial | Spend caps and the per-prospect ceiling ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5), [R-04](../tech-debt-and-risks.md#r-04--p1--cost-the-budget-cap-prices-a-catch-all-submit-at-0)); no API rate limit |
| Destructive actions need confirmation | Met | Delete needs the typed domain (checked on the server); forget and suppress ask first in the UI and CLI (`--yes`) |

## V12 Files and resources

| Requirement | Status | Evidence |
|---|---|---|
| No path traversal when serving files | Met | `outbound/api/app.py::_file_inside`; encoded traversal tested |
| Request size limits | Met | Webhook 1 MB; upload 2 MB |

## V13 API and web services

| Requirement | Status | Evidence |
|---|---|---|
| JSON schema validation of requests | Met | Pydantic models |
| A machine-readable contract, kept in sync | Partial | OpenAPI document regenerated and checked in CI; it lacks security schemes and error responses ([R-18](../tech-debt-and-risks.md#r-18--p3--api-the-openapi-document-is-incomplete)) |
| Webhook authentication | Met | HMAC-SHA256, constant-time compare, timestamp window, idempotency |

## V14 Configuration

| Requirement | Status | Evidence |
|---|---|---|
| A repeatable, automated build | Met | `Dockerfile`, `uv.lock`, CI image job |
| Least privilege at runtime | Partial | Non-root container user; no `cap_drop`, read-only root or `no-new-privileges` in compose |
| Security headers (CSP, nosniff, referrer policy, framing) | Met | `outbound/api/app.py`; not on 500s ([R-17](../tech-debt-and-risks.md#r-17--p3--api-a-500-response-lacks-the-security-headers)) |
| Debug features off in production | Met | No API docs pages; `ENVIRONMENT=production`; JSON logs |

## Summary

| Status | Count |
|---|---|
| Met | 37 |
| Partial | 8 |
| Gap | 6 |
| N/A | 2 |

The gaps that matter most before live use:

- R-08 (prompt fence);
- R-13 (session revocation, HSTS);
- R-07 (unsalted hashes, no retention);
- R-23 (subject access).

## How to refresh this page

Re-check each row's evidence in the code and tests, and update the status when its register entry closes. Re-assess fully when moving to ASVS level 2, or at Phase 6 (users, roles, row-level security).
