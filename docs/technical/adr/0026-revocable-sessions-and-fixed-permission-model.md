---
type: reference
status: accepted
date: 2026-10-23
deciders: "@rahul-trip"
introduced_in: a6d79cc, ffeea2e (migration 0010)
---

# 0026. Revocable, hashed sessions replace signed stateless sessions; permissions, not roles, gate every route

## Context

[0013](0013-single-operator-signed-sessions.md) chose a stateless signed session because there was one operator and nothing to revoke independently of rotating `SESSION_SECRET` (which would sign everyone out at once). Multi-tenancy needs real accounts: a person invited to a workspace, a password they can reset, a session an admin or the person themselves can revoke on one device without touching any other, and more than one role per person (a different role in each workspace they belong to, plus an optional platform-staff role). A stateless session cannot do any of this — there is no row to revoke.

## Decision

Sessions become rows (`SessionRow`): the cookie carries a random token, the server stores only its SHA-256 hash, and `current_user()` checks the row is unexpired and unrevoked on every request — revoking it (sign-out, an admin's "remove this person's access", a password change) takes effect immediately. Users, memberships (one row per `(workspace_id, user_id, role)`), auth tokens (invite/reset/remove-my-data, one-time, hash-stored) and the audit log are new platform tables with **no row-level security** — they are reached only through named queries in `outbound/db/identity.py`, never ad hoc, since there is no `workspace_id` column to scope them by (a user is not owned by any one workspace). Authorization is decided by a fixed `Permission` enum (`outbound/domain/permissions.py`), not by checking a role name at each call site: every route declares exactly one `Permission` it needs, `ROLE_PERMISSIONS`/`PLATFORM_PERMISSIONS` map `MembershipRole`/`PlatformRole` onto permission sets, and a test fails any tenant route that declares none.

## Consequences

- **Good:** sign-out and remote revocation work correctly for the first time. A new route cannot ship without declaring what it needs, checked by a test rather than code review alone. A platform superadmin's cross-workspace read access is expressed the same way — `Principal.superadmin_view` grants exactly the `READ` permission set, nothing more — rather than as a special-cased bypass scattered through route handlers.
- **Bad:** a session lookup is now a database round trip on every request (previously free, since the signature check needed no I/O); mitigated by the session table being small and unindexed-query-free (`token_hash` is the lookup key, indexed, unique).
- **Follow-ups:** `LoginThrottle` ([identity-and-access](../lld/identity-and-access.md)) is in-process memory, correct at today's single-API-process scale but weakening if the API is ever horizontally scaled without a shared throttle store.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep stateless sessions, add a server-side revocation blocklist | The blocklist itself is the state a real session table already is, with none of the "which workspace, which role" structure memberships need |
| Per-route role checks (`if role == "admin"`) instead of a permission enum | Already rejected once implicitly by [0011](0011-operator-input-wins.md)'s spirit of explicit, reviewable rules; a permission enum is testable for completeness in a way ad hoc role checks are not |

## Evidence in the code

- `outbound/db/migrations/versions/0010_identity_and_sessions.py`; `outbound/db/identity.py`; `outbound/api/auth.py`; `outbound/api/deps.py` (`current_user`, `tenant`, `require`, `require_platform`).
- `outbound/domain/permissions.py`.
- `tests/api/test_auth.py`, `tests/domain/test_permissions.py`, `tests/api/test_routes_declare_permission.py`.
