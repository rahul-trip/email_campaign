# Phase 6b — Identity and access

**Goal:** real people sign in and belong to one or more workspaces with a role. Every API route checks what they may do. Platform admins and the alpha's superadmin are separate from workspace roles.

**Depends on:** 6a. **Before starting, delete `web/`** and its CI job (`ci.yml:66-89`): it signs in through the old password form and runs its own browser tests against the same server.

**Gate:**
- **Permissions:**
  - every tenant route is tested against a workspace admin, a member, a platform admin and a superadmin;
  - a route that declares no permission fails CI.
- **Refusals:**
  - a forged `X-Workspace-Id` (a workspace the user is not in) gets 403;
  - a revoked session gets 401;
  - a write made during a superadmin view is refused.
- **Playwright:**
  - a workspace admin invites a member, who sets a password, signs in and sees only that workspace;
  - the password-reset flow works end to end.
- **Actors:** after this phase the API never writes the actor `operator` again; it writes `user:<id>`.

## Scope

**In:**
- users, memberships, invitations, password reset, server-side sessions;
- the permission map and `require()`;
- platform roles (`admin`, `superadmin`), the superadmin read-only view, the audit log;
- the transactional email port;
- `/w/{slug}` URLs, the workspace switcher, the Team page;
- moving the first tenant.

**Out:** these come after the alpha (6f):
- MFA, social sign-in, SSO;
- owner and viewer roles;
- a support role with tenant-granted access;
- self-service email changes. In the alpha, a platform admin changes an email.

## Roles

Fixed in code in `outbound/domain/permissions.py`.

| Permission | Admin | Member | Covers |
|---|:-:|:-:|---|
| `leads.read`, `runs.read`, `review.read`, `usage.read` | ✓ | ✓ | Every read screen |
| `leads.write` | ✓ | ✓ | Add leads, edit, add people, release, retry, resume, research again, change recipient |
| `runs.write` | ✓ | ✓ | Start and cancel runs |
| `review.write` | ✓ | ✓ | Edit, approve (including acknowledged skips), reject, write again, ask for changes |
| `campaigns.write`, `suppressions.write` | ✓ | ✓ | Campaigns; suppress an address or domain; skip one email check |
| `directory.report`, `directory.skip` | ✓ | ✓ | Report a wrong detail, reconfirm (6g); skip the directory when the customer has the ability |
| `mailboxes.own` | ✓ | ✓ | Connect a mailbox; edit the sender identity of a mailbox one owns |
| `mailboxes.manage` | ✓ | | Every mailbox in the workspace |
| `profile.write`, `settings.write` | ✓ | | Company profile; limits and word counts |
| `compliance.write`, `privacy.forget`, `leads.delete` | ✓ | | Country rules, footer, rule switch and skips; forget a person; delete a lead |
| `team.manage`, `integrations.manage`, `data.export`, `workspace.delete` | ✓ | | Team, webhook, export, deletion |

**Platform roles** (`users.platform_role`):

| Permission | Admin | Superadmin |
|---|:-:|:-:|
| `admin.read`, `admin.write` (customers, plans, limits, credits, access time, features, users, settings) | ✓ | ✓ |
| `admin.keys` (reveal and replace vendor keys) | ✓ | ✓ |
| `superadmin.view`: every read permission in **every** workspace, nothing that writes | | ✓ |

## Tasks

### 6b.1 Migration 0010

- [ ] **`users`:**
  - `email` (unique, lower-cased), `name`, `password_hash` (Argon2id);
  - `platform_role` (`admin`, `superadmin` or null), `status` (`active`, `disabled`);
  - `last_login_at`, `terms_version`, `terms_accepted_at`.
- [ ] **`memberships`:** `workspace_id`, `user_id`, `role` (`admin`, `member`); `UNIQUE (workspace_id, user_id)`.
- [ ] **`auth_tokens`:**
  - `purpose` (`invite`, `reset`), `email`;
  - `workspace_id` and `role` (invites only);
  - `token_hash`, `expires_at`, `used_at`, `created_by`.
- [ ] **`sessions`:** `token_hash`, `user_id`, `created_at`, `last_seen_at`, `expires_at`, `revoked_at`, `ip`, `user_agent`, `data` (JSON: OAuth `state` and PKCE verifier for 6c).
- [ ] **`audit_log`:** `actor_user_id`, `workspace_id` (nullable), `action`, `target_type`, `target_id`, `note`, `data` (JSON: before and after). The app and platform roles get INSERT and SELECT only.
- [ ] **RLS:** the `workspaces` policy adds the user's own workspaces through `app.user_id`, so `/api/auth/me` needs no platform role.
- [ ] New `StrEnum`s with matching `CHECK`s. [../SCHEMA.md](../SCHEMA.md) is updated in the same PR.

### 6b.2 Permissions on every route

- [ ] `domain/permissions.py`:
  - a `Permission` `StrEnum`;
  - `ROLE_PERMISSIONS`;
  - `can(principal, permission, resource=None)`, where `resource` carries the owner for `mailboxes.own`.
- [ ] `require(Permission.X)` is a FastAPI dependency, and every tenant route declares one. A test walks the app's routes and fails any route without one.

### 6b.3 Sign-in, invitations and password reset

- [ ] **The `IdentityProvider` port** has a `local` adapter: Argon2id through today's code (`api/auth.py:29-33`). Supabase Auth or WorkOS can replace it after the alpha, by changing this one adapter.
- [ ] **Passwords** follow NIST SP 800-63B-4 for a password that is the only factor:
  - at least 15 characters, and long passphrases allowed;
  - no composition rules;
  - checked against a bundled list of common and breached passwords. No network call.
- [ ] **Throttling:** the existing per-IP throttle (`LoginThrottle`), plus back-off per account.
- [ ] **No account enumeration:** sign-in and "forgot password" give the same answer whether or not the email exists.
- [ ] **Endpoints:**
  - `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/logout-all`;
  - `GET /api/auth/me` returns the user, memberships (id, slug, name, role) and platform role;
  - `POST /api/auth/password/forgot`, `POST /api/auth/password/reset`, `POST /api/auth/password/change`;
  - `GET /api/invitations/{token}` and `POST /api/invitations/{token}/accept`:
    - a new user sets a password;
    - an existing user must be signed in as the invited email.
- [ ] **Team endpoints** (`team.manage`): list, invite (`email`, `role`), resend, revoke, change role, remove.
  - The last admin cannot leave or be demoted.
  - Removing someone revokes their sessions.
- [ ] **Tokens:** invites last 7 days; resets last 30 minutes; both single use and stored as hashes.
- [ ] **The `TransactionalEmail` port:** one adapter (provider chosen by the team: Postmark, Resend or SES) and a fake for tests.
  - Templates: invite, reset, "your password changed".
  - The platform's sending domain has SPF, DKIM and DMARC.
- [ ] **The operator login goes:** `OPERATOR_PASSWORD_HASH` and its hard-coded `{"user": "operator"}` cookie (`api/auth.py:36-57`).

### 6b.4 Sessions and the tenant context

- [ ] **Sessions** are server-side rows. The cookie is `__Host-outbound_session`: HttpOnly, Secure, SameSite=Strict. The `X-Requested-With` check stays.
  - Users: 24 hours idle, 14 days absolute.
  - Platform roles: 8 hours idle, 3 days absolute.
  - Sessions are revoked on removal, a role change, a password reset or a password change (other sessions), disabling, and workspace suspension.
- [ ] **`tenant()`** (in `api/deps.py`) runs these steps:
  1. session → user;
  2. `X-Workspace-Id` → membership and role, or a superadmin view;
  3. workspace status (from 6d: the access level);
  4. binds `user_id` and `workspace_id` to logs;
  5. sets `app.user_id`;
  6. builds the services with `actor = user:<id>`.
- [ ] **Actors:**
  - the webhook becomes `integration:webhook` (`services/webhook.py:92`);
  - `domain/actors.py:is_operator` accepts `integration:`, so webhook input stays protected;
  - `services/journey.py:401-402` already treats `user:` actors as people.

### 6b.5 Platform roles and the superadmin view

- [ ] **`/api/admin/*`** is guarded by `platform_role`. The full console is 6d. This phase adds `POST /api/admin/customers` (company name, website, first admin's email): it creates the workspace and sends the invite, so the alpha can onboard customers.
- [ ] **Superadmin view:** a superadmin opens any `/w/{slug}`.
  - `tenant()` grants every read permission and no write.
  - Every transaction of the request runs `SET TRANSACTION READ ONLY` before the workspace setting.
  - Each (session, workspace) view writes one `audit_log` row.
  - The platform setting `superadmin_enabled` turns the role off. Until 6d's `platform_settings` exists, an environment setting stands in.
- [ ] **The web app** shows a red sticky banner: "Superadmin view of {workspace}, read-only · Exit".

### 6b.6 Web app

- [ ] **Public routes,** outside the signed-in shell: `/sign-in`, `/forgot-password`, `/reset-password`, `/invite/{token}`.
  - The root route (`web2/src/router.tsx:22-29`) splits into a public layout and an app layout.
  - The in-place `Login.tsx` goes.
- [ ] **Every app route** moves under `/w/$slug/…`.
  - `/` opens the last workspace used, stored per browser, or else the first membership.
  - One openapi-fetch middleware sends `X-Workspace-Id`.
  - One QueryClient per workspace is remounted on switching.
  - Cost: about 59 links, 31 `page.goto` calls in `web2/e2e/`, and the tour's `place` values.
- [ ] **Header:**
  - a workspace switcher (replacing the fixed "Workspace" label, `Layout.tsx:84-87`);
  - a user menu: profile, password, sessions, sign out, and **Admin console** for platform roles.
- [ ] **Settings → Team:** members, roles, pending invites, invite, resend, remove.
- [ ] **New UI parts** in `web2/src/components/ui.tsx`: dropdown menu and avatar.
- [ ] **Kept up to date:** the tour (`web2/src/tour/steps.ts`), the "Guided tour" and sign-in sections of [../USER_MANUAL.md](../USER_MANUAL.md), and the `screens.spec.ts` route list.
- [ ] **E2E:** `scripts/e2e_server.py` seeds users and memberships. `helpers.ts` signs in with an email and password.

### 6b.7 Moving the first tenant

- [ ] `scripts/migrate_first_tenant.py`:
  - renames the `default` workspace to the company's name and slug;
  - creates the operator as a user, admin of that workspace and platform `superadmin`.

  It prints its plan and changes nothing without `--apply`. The mailbox move is in 6c.

## Tests that must exist

- The role × route matrix and the "every route declares `require`" walk.
- Forged workspace header (403); revoked or expired session (401); disabled user.
- Superadmin: reads allowed in any workspace; every write refused; view audited; switch off.
- Invites: expiry, reuse refused, wrong email refused, acceptance by an existing user.
- Reset: single use, 30-minute expiry, other sessions revoked.
- Password rules, throttles, no enumeration.
- The last admin protected.
- Actors written as `user:<id>`; the webhook protected as operator input.
- Playwright: invite → set password → onboarding start; reset; switch workspace; superadmin banner.

## Gate record

- Date:
- Permission matrix:
- Playwright flows:
- Checked by:
