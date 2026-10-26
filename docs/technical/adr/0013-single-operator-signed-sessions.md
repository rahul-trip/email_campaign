---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §3](../../PLAN.md#3-decisions-all-confirmed) decision 1; Phase 3 (c3d3228, #1)
---

# 0013. One operator, an Argon2 password and a signed stateless session cookie

## Context

There is one operator until Phase 6, when Supabase auth and multiple users arrive. The app holds personal data and vendor credentials, so it needs real authentication, but a user table, password resets and roles would be built only to be replaced.

## Decision

The operator's password is stored only as an Argon2 hash in the environment (`OPERATOR_PASSWORD_HASH`). Login sets a session cookie signed with `SESSION_SECRET` (itsdangerous), `HttpOnly`, `SameSite=Strict`, `Secure` in production, valid for `SESSION_HOURS` (12). Every write must also carry an `X-Requested-With` header (CSRF). Failed logins are throttled per client address. There is no session table.

## Consequences

- **Good:** nothing to migrate later; no user data to protect; strong defaults (Argon2, strict same-site, CSP).
- **Bad:** a session cannot be revoked before it expires except by rotating `SESSION_SECRET`, which signs everyone out; the throttle is per process and in memory ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)).
- **Follow-ups:** Phase 6 replaces this with Supabase auth and workspace membership.

## Alternatives considered

| Option | Why not |
|---|---|
| A users table with sessions now | Built only to be replaced in Phase 6 |
| Basic auth at the proxy | No CSRF protection, no throttling, credentials on every request |
| No auth on a loopback port behind a VPN | The app is reached through a public proxy |

## Evidence in the code

- `outbound/api/auth.py` (`Sessions`, `LoginThrottle`, `require_operator`, `require_csrf_header`); `outbound/api/routers/auth.py`.
- `tests/api/test_auth_and_errors.py`, `tests/api/test_security.py`.
