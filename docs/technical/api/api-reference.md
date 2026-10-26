---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-27 (5f6dee4)
applies_to: Phase 6b/6c/6d
---

# API reference

Every operation the API serves: **about 147 operations on 130 paths** (up from 59 on 48 before the SaaS transformation — the growth is almost entirely the new `admin`, `mailboxes`, `team`, `usage` and `setup` routers). The machine-readable contract is `web2/openapi.json`. It is generated from the app, and it is the source the web client's types come from. Request and response models are summarised here; their full shape is in that document. Authentication, CSRF, errors and concurrency rules are in [API conventions](api-conventions.md), and they apply to every row below.

**This page is not yet a row-for-row enumeration of all ~147 operations** — the tables below cover every router that existed before Phase 6 in full, and give the new routers' real paths (verified against `outbound/api/routers/*.py`) without yet writing out each one's request/response models and error codes to the same depth. Treat `web2/openapi.json` as authoritative for anything not detailed here; closing this gap is tracked as [R-28](../tech-debt-and-risks.md#r-28--p2--documentation-the-api-reference-has-not-caught-up-with-the-new-routers) rather than left unstated.

**Auth column:**

- **open:** no login;
- **login:** the session cookie (now a real account, not the one shared operator — [identity and access](../lld/identity-and-access.md));
- **login + CSRF:** the session cookie, plus `X-Requested-With` on writes;
- **permission** (new): which `Permission` the route declares via `require()`/`require_platform()` — see [identity and access](../lld/identity-and-access.md#permissions-not-roles-gate-every-route);
- **HMAC:** a signed request, see [webhook integration](webhook-integration.md). The webhook is now per workspace (`/api/intake/webhook/{workspace_id}`), not one platform-wide secret.

**Common errors** apply to every authenticated operation and are not repeated in the rows:

- `401 unauthenticated`;
- `403 missing_header` on writes;
- `422 validation_failed` for a malformed body;
- `404 not_found` for an id that does not exist in this workspace;
- `500 internal_error`.

The "Errors" column lists only the ones specific to that operation.

## Auth

Real accounts and revocable sessions ([ADR 0026](../adr/0026-revocable-sessions-and-fixed-permission-model.md)), not the single operator password. `LoginIn {password}` is now `{email, password}`.

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/auth/login` | CSRF | `LoginIn {email, password}` | 200 `Me`; sets the session cookie | 401 `bad_credentials`, 429 `too_many_attempts` | `IdentityService` |
| `POST /api/auth/logout` | CSRF | — | 204; clears the cookie and revokes the session | — | `IdentityService` |
| `POST /api/auth/logout-others` | login + CSRF | — | 204; revokes every other session for this user | — | `IdentityService` |
| `GET /api/auth/me` | login | — | 200 `Me` (memberships, platform role) | 401 when signed out | — |
| `POST /api/auth/password/forgot` | CSRF | `{email}` | 204 always (never reveals whether the address exists) | — | `IdentityService` |
| `POST /api/auth/password/reset` | CSRF | `{token, password}` | 200 `Me` | 410 expired/used token | `IdentityService` |
| `POST /api/auth/password/change` | login + CSRF | `{current_password, new_password}` | 204 | 401 wrong current password | `IdentityService` |
| `GET /api/auth/invitations/{token}` | open | — | 200 (workspace name, role, inviter) | 410 expired/used/revoked | `IdentityService` |
| `POST /api/auth/invitations/{token}/accept` | CSRF | `{name?, password}` | 200 `Me` | 410 expired/used/revoked | `IdentityService` |
| `POST /api/auth/remove-my-data` | login + CSRF | — | 204; emails a confirmation link | — | `IdentityService` |
| `POST /api/auth/remove-my-data/confirm` | CSRF | `{token}` | 204 | 410 expired/used | `IdentityService` |

## Team

| Method and path | Auth | Permission | Calls |
|---|---|---|---|
| `GET /api/team` | login | `TEAM_READ` | Members, roles, pending invitations |
| `POST /api/team/invitations` | login + CSRF | `TEAM_MANAGE` | `IdentityService.invite` |
| `POST /api/team/invitations/{invitation_id}/resend` | login + CSRF | `TEAM_MANAGE` | Revokes the old token, issues a new one |
| `DELETE /api/team/invitations/{invitation_id}` | login + CSRF | `TEAM_MANAGE` | Revokes a pending invitation |
| `PATCH /api/team/members/{user_id}` | login + CSRF | `TEAM_MANAGE` | Change a member's role |
| `DELETE /api/team/members/{user_id}` | login + CSRF | `TEAM_MANAGE` | Remove a member (refused if they are the last admin) |

## Mailboxes

See [mailboxes and OAuth](../lld/mailboxes-and-oauth.md).

| Method and path | Auth | Permission | Calls |
|---|---|---|---|
| `GET /api/mailboxes` | login | `SETTINGS_READ` | List this workspace's connected mailboxes |
| `POST /api/mailboxes/oauth/start` | login + CSRF | `MAILBOXES_OWN` | Begins the Microsoft/Google PKCE flow, returns the authorize URL |
| `POST /api/mailboxes/oauth/finish` | login + CSRF | `MAILBOXES_OWN` | Exchanges the authorization code, stores the sealed tokens |
| `POST /api/mailboxes/imap` | login + CSRF | `MAILBOXES_OWN` | Connects an IMAP account (host, address, app password); tested before saving |
| `POST /api/mailboxes/{mailbox_id}/test` | login + CSRF | `MAILBOXES_OWN`/`MANAGE` (own vs. any) | Re-checks the connection and DNS |
| `POST /api/mailboxes/{mailbox_id}/pause`, `/resume` | login + CSRF | `MAILBOXES_OWN`/`MANAGE` | Stops/resumes delivery through it |
| `PUT /api/mailboxes/{mailbox_id}/sender` | login + CSRF | `MAILBOXES_OWN`/`MANAGE` | The sender identity (name, title, greeting, voice examples) used when drafting from it |
| `DELETE /api/mailboxes/{mailbox_id}` | login + CSRF | `MAILBOXES_OWN`/`MANAGE` | Disconnects it; the stored credential is deleted |

## Usage and setup

| Method and path | Auth | Permission | Calls |
|---|---|---|---|
| `GET /api/usage` | login | `SETTINGS_READ` | The workspace's `Quota` ([plans, credits and admin](../lld/plans-credits-and-admin.md)) |
| `POST /api/usage/request-credits` | login + CSRF | `SETTINGS_WRITE` | Sends a notice to platform staff |
| `POST /api/companies/resume`, `/api/companies/{company_id}/resume`, `/api/targets/resume` | login + CSRF | `LEADS_WRITE` | Retries work that was waiting on credit |
| `GET /api/setup` | login | `SETTINGS_READ` | What a new workspace still has to do (onboarding checklist) |

## Integrations

| Method and path | Auth | Permission | Calls |
|---|---|---|---|
| `GET /api/integrations/webhook` | login | `INTEGRATIONS_MANAGE` | This workspace's intake webhook URL and whether a secret is set |
| `POST /api/integrations/webhook/rotate` | login + CSRF | `INTEGRATIONS_MANAGE` | Issues a new webhook secret, invalidating the old one |

## Platform admin

Behind `require_platform`, never a workspace permission — see [identity and access](../lld/identity-and-access.md) and [plans, credits and admin](../lld/plans-credits-and-admin.md). Selected paths (the full set is in `outbound/api/routers/admin.py`, 45 operations):

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/admin/overview`, `/customers` | `ADMIN_READ` | Platform-wide figures; the customer list |
| `GET /api/admin/customers/{workspace_id}` | `ADMIN_READ` | One customer's detail: plan, quota, members, mailboxes |
| `PATCH /api/admin/customers/{workspace_id}/plan`, `/status` | `ADMIN_WRITE` | Change a customer's plan or `WorkspaceStatus` |
| `POST /api/admin/customers/{workspace_id}/access` | `ADMIN_WRITE` | Set `access_until` |
| `PUT /api/admin/customers/{workspace_id}/overrides` | `ADMIN_WRITE` | Replace a customer's active `Override`s |
| `POST /api/admin/customers/{workspace_id}/grants`, `DELETE .../grants/{grant_id}` | `ADMIN_WRITE` | Issue or revoke a `Grant` |
| `POST /api/admin/customers/{workspace_id}/resume` | `ADMIN_WRITE` | Release leads waiting on credit |
| `PATCH /api/admin/customers/{workspace_id}/members/{user_id}`, `DELETE .../members/{user_id}` | `ADMIN_WRITE` | Platform-side team management |
| `POST /api/admin/customers/{workspace_id}/mailboxes/{mailbox_id}/reconnect` | `ADMIN_WRITE` | Force a customer to reconnect a mailbox |
| `GET /api/admin/users`, `POST .../disable`, `/enable`, `/sign-out`, `PUT .../platform-role` | `ADMIN_READ`/`ADMIN_WRITE` | Platform staff account management |
| `GET /api/admin/plans`, `PUT /plans/default`, `PUT /plans/{code}` | `ADMIN_READ`/`ADMIN_WRITE` | The plan catalog |
| `GET /api/admin/vendors`, `PUT .../key`, `POST .../rollback`, `POST .../reveal`, `PUT .../paused`, `PATCH /vendors/llm`, `PUT .../cap` | `ADMIN_KEYS` | Platform vendor keys, encrypted, versioned, with audited reveal and rollback |
| `GET /api/admin/directory`, `POST /directory/flags/{flag_id}/resolve`, `GET /directory/history`, `GET /directory/entries`, `POST/PATCH/DELETE .../entries/{entry_id}`, `GET /directory/companies`, `PUT/DELETE .../companies/{domain}` | `ADMIN_READ`/`ADMIN_WRITE` | The [lead directory](../lld/lead-directory.md) review and editing screen |
| `GET /api/admin/settings`, `PATCH /settings` | `ADMIN_WRITE` | The platform's own settings (kill switch, etc.) |
| `GET /api/admin/audit`, `/audit.csv` | `ADMIN_READ` | The audit log |

## Intake webhook

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/intake/webhook/{workspace_id}` | HMAC (`X-Signature`, `X-Timestamp`), per-workspace secret made in Settings → Integrations | Raw JSON, ≤ 1 MB: `event_id`, `targets` (1–200) | 200 object (accepted and duplicate counts) | 401 `bad_signature`, `stale_timestamp`; 413 `body_too_large`; 422 `bad_json`, `missing_event_id`, `bad_targets`; 503 `webhook_disabled` | `WebhookService.receive` |

## Targets

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/targets` | login + CSRF | `TargetIn {company?, website?, email?, person?, title?, linkedin?, country?, notes?, priority 1–9?, campaign_id?, validate_only}` | 200 `IntakeOut` (per row: status, domain, reason) | — | `IntakeService.run` |
| `POST /api/targets/upload` | login + CSRF | multipart: `file` (CSV or XLSX, ≤ 2 MB), `campaign_id?`, `preview` (default **true**: checks and saves nothing) | 200 `IntakeOut` | 422 `invalid_request` (too large, unreadable) | `load_rows` → `IntakeService.run` |
| `GET /api/targets/waiting` | login | — | 200 `list[WaitingRowOut]` | — | `IntakeService.needing_confirmation` |
| `POST /api/targets/{row_id}/confirm` | login + CSRF | `ConfirmIn {domain}` | 200 `RowOut` | 409 `action_not_allowed` | `IntakeService.confirm` |
| `PATCH /api/companies/{company_id}` | login + CSRF | `CompanyPatch {row_version, name?, country_code (2 letters)?, priority 1–9?, campaign_id?, …}` | 200 `CompanyOut` | 409 `version_conflict` | `LeadService.update` |

## Review

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `GET /api/review` | login | — | 200 `list[ReviewItemOut]` (message, company, contact, `flagged`, `skips`) | — | `ReviewService.queue` |
| `GET /api/review/{message_id}` | login | — | 200 `ReviewDetailOut` (item, notes) | — | `ReviewService.show` |
| `POST /api/review/{message_id}/approve` | login + CSRF | `ApproveIn {edited_body?, row_version?, acknowledge_skips}` | 200 `MessageOut` | 409 `version_conflict`; 409 `action_not_allowed` (skips not acknowledged, address suppressed, footer removed, already reviewed) | `ReviewService.approve` |
| `POST /api/review/{message_id}/reject` | login + CSRF | `RejectIn {reason}` | 200 `MessageOut` | 409 `action_not_allowed` (no reason, already reviewed) | `ReviewService.reject` |

## Leads, people and addresses

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `GET /api/companies` | login | query `status?`, `hold_reason?`, `campaign_id?`, `q?`, `limit` 1–200 (50), `offset` | 200 `CompanyPage` | — | `LeadService.search` |
| `GET /api/companies/{company_id}` | login | — | 200 `LeadOut` (company, people with addresses and consents, messages, notes) | — | `LeadService.detail` |
| `GET /api/companies/{company_id}/journey` | login | — | 200 `JourneyOut` | — | `LeadService.journey` |
| `GET /api/companies/{company_id}/timeline` | login | — | 200 `list[TimelineOut]` (events) | — | `LeadService.timeline` |
| `GET /api/companies/{company_id}/waterfall` | login | — | 200 `list[WaterfallOut]` (vendor calls) | — | `LeadService.waterfall` |
| `POST /api/companies/{company_id}/retry` | login + CSRF | — | 200 `CompanyOut` | 409 not failed | `LeadService.retry` |
| `POST /api/companies/{company_id}/release-hold` | login + CSRF | `ReleaseIn {resume_to?}` | 200 `CompanyOut` | 409 not held; no default resume point; a country-rule hold whose cause is unchanged | `LeadService.release_hold` |
| `POST /api/companies/{company_id}/requalify` | login + CSRF | — | 200 `CompanyOut` | 409 not disqualified | `LeadService.requalify` |
| `POST /api/companies/{company_id}/policy-skip` | login + CSRF | `PolicySkipIn {from_stage, reason (1–1000)}` | 200 `CompanyOut` | 409 nothing left to check, or the stage is later than where the rule stopped the lead | `LeadService.skip_policy` |
| `DELETE /api/companies/{company_id}/policy-skip` | login + CSRF | — | 200 `CompanyOut` | 409 at or after approval | `LeadService.revoke_policy_skip` |
| `POST /api/companies/release-policy-holds` | login + CSRF | — | 200 object `{released}` | — | `LeadService.release_policy_holds` |
| `POST /api/companies/{company_id}/change-recipient` | login + CSRF | `RecipientIn {contact_id}` | 200 `CompanyOut` | 409 person not at the lead, not workable, or the lead is past the mailbox | `LeadService.change_recipient` |
| `POST /api/companies/{company_id}/people` | login + CSRF | `PersonIn {full_name (1–200), title?, email?, consent_basis? + consent_evidence? (both or neither)}` | 201 `ContactOut` | 409 a one-word name without an email | `LeadService.add_person` |
| `PATCH /api/contacts/{contact_id}` | login + CSRF | `PersonPatch {full_name?, title?, email?}` | 200 `ContactOut` | — | `LeadService.update_person` |
| `POST /api/contacts/{contact_id}/consents` | login + CSRF | `ConsentIn {basis, evidence}` | 201 `ConsentOut` | — | `LeadService.record_consent` |
| `POST /api/contacts/{contact_id}/confirm` | login + CSRF | — | 200 `ContactOut` | 409 not unconfirmed | `LeadService.confirm_person` |
| `DELETE /api/contacts/{contact_id}` | login + CSRF | — | 204 | 409 already written to | `LeadService.remove_person` |
| `POST /api/contact-emails/{email_id}/skip-verification` | login + CSRF | `SkipCheckIn {reason (1–1000)}` | 200 `ContactOut` | 409 erased or suppressed address | `LeadService.skip_email_verification` |
| `DELETE /api/contact-emails/{email_id}/skip-verification` | login + CSRF | — | 200 `ContactOut` | 409 after approval | `LeadService.restore_email_verification` |

## Runs and reports

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/runs` | login + CSRF | `RunIn {limit 1–500 (50), only[], mode manual\|discovery\|mixed, discover 1–50 (10), campaign?}` | **202** `RunOut` (queued) | — | `RunService.queue` |
| `GET /api/runs` | login | — | 200 `list[RunOut]` (the 20 most recent) | — | `RunService.recent` |
| `GET /api/runs/{run_id}` | login | — | 200 `RunOut` (live cost while running) | — | `RunService.get` |
| `POST /api/runs/{run_id}/cancel` | login + CSRF | — | 200 `RunOut` | — | `RunService.cancel` |
| `GET /api/status` | login | — | 200 `StatusOut` (counts by status, review queue, holds) | — | `ReportService.status` |
| `GET /api/reports/quality` | login | — | 200 `QualityOut` | — | `ReportService.quality` |
| `GET /api/reports/cost` | login | query `days` 1–365 (30) | 200 `CostOut` | — | `ReportService.cost` |

## Settings

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `GET /api/settings/sender-profile` | login | — | 200 object | — | `SettingsService.sender_profile` |
| `PUT /api/settings/sender-profile` | login + CSRF | `SenderProfileIn` (known fields only, with length limits; `reviewed_at` ignored, set by the server) | 200 object | 422 `invalid_request` | `SettingsService.update_sender_profile` |
| `GET /api/settings/workspace` | login | — | 200 object | — | `SettingsService.workspace_settings` |
| `PUT /api/settings/workspace` | login + CSRF | `WorkspaceSettingsIn {safe_to_send_only?, budget_per_prospect_micro_usd 0–100,000,000 or null?, few_shot_examples 0–20?, timezone?, country_policy_enabled?, footer_enabled?}` | 200 object | 422 `send_enabled` before Phase 5; unknown fields | `SettingsService.update_workspace_settings` |
| `GET /api/settings/campaigns` | login | — | 200 `list[CampaignOut]` | — | `SettingsService.campaigns` |
| `POST /api/settings/campaigns` | login + CSRF | `CampaignIn {name, target_titles, icp_description?, min_fit_score 0–100 (60), research_questions ≤ 3, cadence_days}` | 201 `CampaignOut` | — | `SettingsService.create_campaign` |
| `PATCH /api/settings/campaigns/{campaign_id}` | login + CSRF | `CampaignPatch` | 200 `CampaignOut` | — | `SettingsService.update_campaign` |
| `GET /api/settings/policies` | login | — | 200 `list[PolicyOut]` | — | `SettingsService.policies` |
| `PUT /api/settings/policies/{country_code}` | login + CSRF | `PolicyIn {rule, requires_corporate_subscriber, allowed_provenance?, footer_template?, reviewed_by?}` | 200 `PolicyOut` (version bumped on change) | — | `SettingsService.save_policy` |
| `DELETE /api/settings/policies/{country_code}` | login + CSRF | — | 204 | — | `SettingsService.delete_policy` |
| `GET /api/settings/suppressions` | login | — | 200 `list[SuppressionOut]` (kind, reason, a fingerprint of the hash; never the value) | — | `SettingsService.suppressions` |
| `POST /api/settings/suppressions` | login + CSRF | `SuppressionIn {kind, value, reason}` | 201 object `{added}` | — | `SettingsService.suppress` |
| `GET /api/settings/mailboxes` | login | — | 200 `list[MailboxOut]` | — | `SettingsService.mailboxes` |
| `POST /api/settings/mailboxes` | login + CSRF | `MailboxIn {address, credentials_ref, daily_cap 1–500 (10), …}` | 201 `MailboxOut` | — | `SettingsService.add_mailbox` |
| `POST /api/settings/mailboxes/{mailbox_id}/dns-check` | login + CSRF | — | 200 object (SPF, DKIM, DMARC results) | — | `SettingsService.dns_check` |

## Privacy

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/privacy/forget` | login + CSRF | `ForgetIn {email}` | 200 `PrivacyOut` (found, messages cancelled, drafts deleted, drafts left) | — | `PrivacyService.forget` |
| `POST /api/companies/{company_id}/delete` | login + CSRF | `DeleteLeadIn {confirm_domain, also_suppress_domain}` | 200 `DeleteLeadOut` | 422 domain does not match; 409 the lead was emailed | `PrivacyService.delete_lead` |
| `POST /api/contacts/{contact_id}/suppress` | login + CSRF | — | 200 `PrivacyOut` | — | `PrivacyService.suppress_contact` |
| `POST /api/companies/{company_id}/suppress` | login + CSRF | — | 200 `PrivacyOut` | — | `PrivacyService.suppress_company` |

## Service

| Method and path | Auth | Response |
|---|---|---|
| `GET /api/health` | open | 200 `{"status": "ok"}`. Does not check the database ([R-06](../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database)) |
| `GET /api/openapi.json` | login | The OpenAPI document. Left out of the document itself |
| any other `/api/...` | — | 404 `no_such_endpoint` |

## Untyped responses

Eight operations return a plain object rather than a named model, so the generated client types them loosely ([R-18](../tech-debt-and-risks.md#r-18--p3--api-the-openapi-document-is-incomplete)):

- the webhook;
- `release-policy-holds`;
- sender profile GET and PUT;
- workspace settings GET and PUT;
- `POST /api/settings/suppressions`;
- `dns-check`.

## How to refresh this page

```bash
uv run python -m scripts.export_openapi > /tmp/openapi.json      # or read web2/openapi.json
jq '.paths | length' /tmp/openapi.json
jq '[.paths[] | to_entries[] | select(.key|test("get|post|put|patch|delete"))] | length' /tmp/openapi.json
jq -r '.paths | to_entries[] | .key as $p | .value | to_entries[] | "\(.key|ascii_upcase) \($p) \(.value.summary)"' /tmp/openapi.json
grep -n "@router\.\(get\|post\|put\|patch\|delete\)" outbound/api/routers/*.py
```

Compare every row with the list and with its router function; then check the request models in `outbound/api/schemas.py`.
