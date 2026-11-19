---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-27 (5f6dee4)
applies_to: Phase 6b/6c/6d
---

# API reference

Every operation the API serves: **about 147 operations on 130 paths** (up from 59 on 48 before the SaaS transformation — the growth is almost entirely the new `admin`, `mailboxes`, `team`, `usage` and `setup` routers). The machine-readable contract is `web2/openapi.json`. It is generated from the app, and it is the source the web client's types come from. Every money figure a workspace sees is AI credits: integer `*_credits_milli`/`credits_milli` fields are thousandths of a credit, plan and grant amounts are whole credits. Only the admin console's `cost_micro_usd` fields are dollars. Request and response models are summarised here; their full shape is in that document. Authentication, CSRF, errors and concurrency rules are in [API conventions](api-conventions.md), and they apply to every row below.

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
| `POST /api/auth/account/delete` | login + CSRF | `{password}` | 204, session cleared | 400 wrong password; 409 `last_admin`, `last_superadmin` | `IdentityService.delete_account` |
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
| `GET /api/usage` | login | `SETTINGS_READ` | `UsageOut`: the plan, `credits {monthly, granted, allowance, used_milli, remaining_milli}` (AI credits; `_milli` in thousandths), grants, waiting work, access ([plans, credits and admin](../lld/plans-credits-and-admin.md)) |
| `POST /api/usage/request-credits` | login + CSRF | `SETTINGS_WRITE` | `RequestCreditsIn {amount?, note}` (AI credits wanted; one of the two required). Sends a notice to platform staff |
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
| `POST /api/admin/customers/{workspace_id}/grants`, `DELETE .../grants/{grant_id}` | `ADMIN_WRITE` | Issue or revoke a `Grant`: `GrantIn {amount (AI credits), expires_at?, note, resume_now}` |
| `POST /api/admin/customers/{workspace_id}/resume` | `ADMIN_WRITE` | Release leads waiting on credit |
| `PATCH /api/admin/customers/{workspace_id}/members/{user_id}`, `DELETE .../members/{user_id}` | `ADMIN_WRITE` | Platform-side team management |
| `POST /api/admin/customers/{workspace_id}/mailboxes/{mailbox_id}/reconnect` | `ADMIN_WRITE` | Force a customer to reconnect a mailbox |
| `DELETE /api/admin/users/{user_id}` | `ADMIN_WRITE` and superadmin | — | 204 | 403 not a superadmin; 409 `not_yourself`, `last_superadmin`, `last_admin`; 404 | `IdentityService.delete_account` |
| `GET /api/admin/users`, `POST .../disable`, `/enable`, `/sign-out`, `PUT .../platform-role` | `ADMIN_READ`/`ADMIN_WRITE` | Platform staff account management |
| `GET /api/admin/plans`, `PUT /plans/default`, `PUT /plans/{code}`, `PUT /plans/credit-value` | `ADMIN_READ` / `ADMIN_PLANS` (superadmins) | The plan catalog (`monthly_credits`, `max_prospect_budget_credits`, …), the default plan and `credit_value_micro_usd`; `PlansOut.can_edit` says whether the caller may change them |
| `PUT /api/admin/models/{code}`, `DELETE /api/admin/models/{code}`, `POST /api/admin/models/{code}/test`, `PUT /api/admin/models/default` | `ADMIN_KEYS` | The AI model catalog: `LlmModelIn {label, provider, model, base_url, temperature, max_tokens, reasoning_effort, input_credits, output_credits, api_key?}` (`api_key` null keeps the key, "" removes it; never returned); `ChooseModelsIn {default_model, writer_model, extract_model}` (writer and extraction models must share the default's provider and address). `VendorsOut` lists `models` (key masked), `default_model`, `writer_model`, `extract_model` and `providers` (`needs_key`, `needs_base_url`, `default_base_url`) |
| `GET /api/admin/vendors`, `PUT .../key`, `POST .../rollback`, `POST .../reveal`, `PUT .../paused`, `PATCH /vendors/llm`, `PUT .../cap` | `ADMIN_KEYS` | Platform vendor keys, encrypted, versioned, with audited reveal and rollback. `VendorOut` has `credits_milli`, `cost_micro_usd` and `cap_credits`; `VendorCapIn {cap_credits}`; `LlmSettingsIn.charges` replaces every model's charge (`{model, per_million_input, per_million_output}` in AI credits) and `VendorsOut.llm_charges` lists them |
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
| `PATCH /api/companies/{company_id}` | login + CSRF | `CompanyPatch {row_version, name?, country_code (2 letters)?, priority 1–9?, campaign_id?, …}` | 200 `CompanyOut` (every `CompanyOut` carries `hot`: the fit score is above 80) | 409 `version_conflict` | `LeadService.update` |

## Review

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `GET /api/review` | login | query `limit` (1 to 100, default 100), `best` (best-fitting lead first instead of oldest first), `slim` (leave out each lead's research record) | 200 `list[ReviewItemOut]` (message, company, contact, `flagged`, `skips`) | 422 for a `limit` outside 1 to 100 | `ReviewService.queue` |
| `GET /api/review/{message_id}` | login | — | 200 `ReviewDetailOut` (item, notes) | — | `ReviewService.show` |
| `POST /api/review/{message_id}/approve` | login + CSRF | `ApproveIn {edited_body?, row_version?, acknowledge_skips}` | 200 `MessageOut` | 409 `version_conflict`; 409 `action_not_allowed` (skips not acknowledged, address suppressed, footer removed, already reviewed) | `ReviewService.approve` |
| `POST /api/review/{message_id}/reject` | login + CSRF | `RejectIn {reason}` | 200 `MessageOut` | 409 `action_not_allowed` (no reason, already reviewed) | `ReviewService.reject` |

## Leads, people and addresses

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `GET /api/companies` | login | query `status?`, `hold_reason?`, `campaign_id?`, `q?`, `waiting_for_credits?`, `min_fit?` 0–100, `hot?` (fit above 80; unscored is neither), `bucket?` (`ready` \| `working` \| `decision` \| `screened_out` \| `done`: where the lead stands for a person, see `domain/outcomes.py`), `source?` (`CompanySource`), `country?` (2 letters, any case), `sort` `newest` (default, date added) \| `fit` \| `updated` \| `name` \| `status` \| `country` \| `source` \| `priority`, `direction?` `asc` \| `desc` (default: newest, best fit and latest change first; the rest A to Z; empty values last either way), `include?` `summary`, `limit` 1–200 (50), `offset` | 200 `CompanyPage {items: list[CompanyRowOut], total}` (every `CompanyOut` also carries `failure_kind`, `attempts`, `max_tries` and `bucket`); with `include=summary` each row's `summary` is `LeadSummaryOut {contact_name, contact_title, email_status, credits_milli}` (first-ranked active or candidate person, their main address status, the AI credits the lead used, in thousandths), else null | 422 bad `sort`, `direction`, `min_fit` or `country` | `LeadService.search`, `ReportService.lead_summaries` |
| `GET /api/companies/{company_id}` | login | — | 200 `LeadOut` (company, people with addresses and consents, messages, notes) | — | `LeadService.detail` |
| `GET /api/companies/{company_id}/journey` | login | — | 200 `JourneyOut` | — | `LeadService.journey` |
| `GET /api/companies/{company_id}/timeline` | login | — | 200 `list[TimelineOut]` (events) | — | `LeadService.timeline` |
| `GET /api/companies/{company_id}/waterfall` | login | — | 200 `list[WaterfallOut {at, provider, operation, outcome, credits_milli, latency_ms, contact_id, asked, got}]` (vendor calls; `asked` and `got` are empty for calls made before they were kept) | — | `LeadService.waterfall` |
| `POST /api/companies/{company_id}/retry` | login + CSRF | — | 200 `CompanyOut` | 409 not failed | `LeadService.retry` |
| `POST /api/companies/find-email-again` | login + CSRF (`leads:write`) | `FindEmailAgainIn {company_ids 1–200}` | 200 `FindEmailAgainOut {queued_run_id \| null, asked, skipped}`: each lead held on a catch-all address has its catch-all people (else the first-ranked one) marked for a fresh search and moves to `contacts_found`; one run is queued for all; other leads are skipped, not refused | 422 empty list | `LeadService.retry_email_for_companies` |
| `POST /api/companies/{company_id}/release-hold` | login + CSRF | `ReleaseIn {resume_to?}` | 200 `CompanyOut` | 409 not held; no default resume point; a country-rule hold whose cause is unchanged | `LeadService.release_hold` |
| `POST /api/companies/{company_id}/requalify` | login + CSRF | — | 200 `CompanyOut` | 409 not disqualified | `LeadService.requalify` |
| `POST /api/companies/{company_id}/policy-skip` | login + CSRF | `PolicySkipIn {from_stage, reason (1–1000)}` | 200 `CompanyOut` | 409 nothing left to check, or the stage is later than where the rule stopped the lead | `LeadService.skip_policy` |
| `DELETE /api/companies/{company_id}/policy-skip` | login + CSRF | — | 200 `CompanyOut` | 409 at or after approval | `LeadService.revoke_policy_skip` |
| `POST /api/companies/release-policy-holds` | login + CSRF | — | 200 object `{released}` | — | `LeadService.release_policy_holds` |
| `POST /api/companies/{company_id}/change-recipient` | login + CSRF | `RecipientIn {contact_id}` | 200 `CompanyOut` | 409 person not at the lead, not workable, or the lead is past the mailbox | `LeadService.change_recipient` |
| `POST /api/companies/{company_id}/people` | login + CSRF | `PersonIn {full_name (1–200), title?, email?, consent_basis? + consent_evidence? (both or neither)}` | 201 `ContactOut` | 409 a one-word name without an email | `LeadService.add_person` |
| `PATCH /api/contacts/{contact_id}` | login + CSRF | `PersonPatch {full_name?, title?, email?, linkedin_url?}` (`linkedin_url` any LinkedIn profile link, made plain and kept as yours; `""` removes it) | 200 `ContactOut` | 422 not a profile link, or another person here has it | `LeadService.update_person` |
| `POST /api/companies/{company_id}/find-people` | login + CSRF (`LEADS_WRITE`) | — | 200 `PeopleFoundOut {found, added, works_here, unsure, retried}`: up to two searches for the campaign's job titles (Founder, CEO, CTO without a campaign) and one model call; new people only; a lead that failed at the people or email step with someone new to write to goes back to that step | 409 no search key | `LeadService.find_people_again` |
| `POST /api/contacts/{contact_id}/consents` | login + CSRF | `ConsentIn {basis, evidence}` | 201 `ConsentOut` | — | `LeadService.record_consent` |
| `POST /api/contacts/{contact_id}/confirm` | login + CSRF | — | 200 `ContactOut` | 409 not unconfirmed | `LeadService.confirm_person` |
| `DELETE /api/contacts/{contact_id}` | login + CSRF | — | 204 | 409 already written to | `LeadService.remove_person` |
| `POST /api/contact-emails/{email_id}/skip-verification` | login + CSRF | `SkipCheckIn {reason (1–1000)}` | 200 `ContactOut` | 409 erased or suppressed address | `LeadService.skip_email_verification` |
| `DELETE /api/contact-emails/{email_id}/skip-verification` | login + CSRF | — | 200 `ContactOut` | 409 after approval | `LeadService.restore_email_verification` |

## Runs and reports

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/runs` | login + CSRF | `RunIn {limit 1–500 (50; the web app no longer sends it), only[], mode manual\|discovery\|mixed, discover 1–50 (10), campaign?}` | **202** `RunOut` (queued) | — | `RunService.queue` |
| `GET /api/runs` | login | — | 200 `list[RunOut]` (the 20 most recent) | — | `RunService.recent` |
| `GET /api/runs/auto-discovery` | login (`runs.read`) | — | 200 `AutoDiscoveryOut {reason, campaign, last_search, next_search, per_day, review_limit, waiting_for_review}`; `reason` is null when a search is due, else `off`, `no_campaign`, `no_credits`, `run_in_progress`, `review_full`, `backlog` or `not_yet` | — | `AutoDiscovery.state` |
| `GET /api/runs/plan` | login (`runs.read`) | — | 200 `DiscoveryPlanOut {campaign, sources: list[PlannedSourceOut {source, suited, why_not, share, found, qualified, rate}]}`: the sources the next discovery run would ask for the active campaign's brief, in order, then the unsuited ones with the reason; a source whose key is missing is skipped only when the run starts. Read-only | — | `ReportService.discovery_plan` |
| `GET /api/runs/{run_id}` | login | — | 200 `RunOut` (live cost while running) | — | `RunService.get` |
| `POST /api/runs/{run_id}/cancel` | login + CSRF | — | 200 `RunOut` | — | `RunService.cancel` |
| `GET /api/runs/{run_id}/searches` | login (`runs.read`) | — | 200 `list[DiscoverySearchOut {query, new_leads, already_leads, source, angle, found, pages[]}]` | 404 | `RunService.searches` |
| `GET /api/runs/{run_id}/candidates` | login (`runs.read`) | — | 200 `list[CandidateOut {id, run_id, name, domain, sources[], source_urls[], description, evidence, screen_score, rank_score, verdict, reason, company_id}]`, best ranked first | 404 | `CandidateService.for_run` |
| `POST /api/candidates/{candidate_id}/promote` | login + CSRF (`leads.write`) | `PromoteIn {domain?}` | 200 `CandidateOut` (`accepted`, with `company_id`) | 404; 422 already a lead, no website known and none given, or intake refused it | `CandidateService.promote` |
| `GET /api/linkedin` | login | query `state` (`drafted` default \| `sent` \| `skipped`), `hot?` (fit above 80, or only the rest), `q?` (company, domain or person), `min_fit?` 0–100, `no_email?` (leads nobody could find a provable address for, or only the others), `country?` (2 letters), `sort?` `fit` \| `newest` \| `company` (default: best fit first for waiting messages, newest first for the rest), `direction?` `asc` \| `desc`, `limit` 1–200 (50), `offset` | 200 `LinkedInDraftPage {items: list[LinkedInDraftRowOut {item, company_name, domain, person, title, profile, fit_score, hot, fit_reason, country_code, company_status, failure_kind, company_bucket}], total}` | 422 bad `state`, `sort` or `min_fit` | `LinkedInService.page` |
| `GET /api/status` | login | — | 200 `StatusOut` (counts by status, review queue, `waiting_hot` (of those, the hot ones), holds, and `buckets`: leads per bucket) | — | `ReportService.status` |
| `GET /api/reports/quality` | login | — | 200 `QualityOut` | — | `ReportService.quality` |
| `GET /api/reports/cost` | login | query `days` 1–365 (30) | 200 `CostOut` | — | `ReportService.cost` |
| `GET /api/reports/daily` | login (`reports:read`) | query `days` 1–90 (14) | 200 `DailyOut {days: list[DayOut {day, leads, approved, reviewed, sent, credits_milli}], review_streak}`: one row per UTC day, oldest first, today included; `reviewed` counts approvals and rejections by a person (not `auto` or the system); `review_streak` is consecutive days with a review ending today or yesterday | 422 `days` out of range | `ReportService.daily` |
| `GET /api/reports/fit` | login (`reports:read`) | — | 200 `FitOut {campaign_id, campaign, min_fit_score, bands: list[FitBandOut {start, count}], scored, unscored}`: the active campaign's companies (every company when none is active) in fit bands 0, 10 … 90 (90 holds 90–100) | — | `ReportService.fit` |
| `GET /api/reports/funnel` | `reports:read` | `days` (1–365, default 30) | 200 `FunnelOut`: companies discovery named (and how many the model scored), screening verdicts, leads added and where they are now (`waiting`, `failed:<stage>`, `held:<reason>`, a status), and per-vendor calls and failures | 422 for `days` out of range | `ReportService.funnel` |
| `GET /api/reports/sources` | `reports:read` | — | 200 `SourceYieldOut[]`: per discovery source over 90 days, companies named, leads, passed the fit gate, rate | — | `ReportService.sources` |

## Settings

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `GET /api/settings/sender-profile` | login | — | 200 object | — | `SettingsService.sender_profile` |
| `PUT /api/settings/sender-profile` | login + CSRF | `SenderProfileIn` (known fields only, with length limits; `reviewed_at` ignored, set by the server) | 200 object | 422 `invalid_request` | `SettingsService.update_sender_profile` |
| `GET /api/settings/workspace` | login | — | 200 object | — | `SettingsService.workspace_settings` |
| `PUT /api/settings/workspace` | login + CSRF | `WorkspaceSettingsIn {safe_to_send_only?, budget_per_prospect_credits 0–1,000,000 or null?, few_shot_examples 0–20?, timezone?, country_policy_enabled?, footer_enabled?, auto_discovery?, auto_discovery_per_day 1–6?, auto_discovery_review_limit 1–500?, auto_approve_cold?}` | 200 object | 422 `send_enabled` before Phase 5; unknown fields | `SettingsService.update_workspace_settings` |
| `GET /api/settings/campaigns` | login | — | 200 `list[CampaignOut]` (each with `status` `active` or `paused`; one is active) | — | `SettingsService.campaigns` |
| `POST /api/settings/campaigns` | login + CSRF | `CampaignIn {name, target_titles, icp_description?, min_fit_score 0–100 (60), research_questions ≤ 3, cadence_days}` | 201 `CampaignOut` | — | `SettingsService.create_campaign` |
| `PATCH /api/settings/campaigns/{campaign_id}` | login + CSRF | `CampaignPatch` (`icp_brief` is cleaned by `domain.brief.Brief`) | 200 `CampaignOut` | — | `SettingsService.update_campaign` |
| `POST /api/settings/campaigns/{campaign_id}/brief/regenerate` | login + CSRF (`campaigns:write`) | — | 200 `CampaignOut` with a new `icp_brief` | 404 no such campaign | `SettingsService.regenerate_brief` |
| `POST /api/settings/campaigns/{campaign_id}/activate` | login + CSRF (`campaigns:write`) | — | 200 `CampaignOut`: the campaign is the active one and the previous one is paused | 404 | `SettingsService.activate_campaign` |
| `POST /api/settings/campaigns/{campaign_id}/pause` | login + CSRF (`campaigns:write`) | — | 200 `CampaignOut` (paused) | 404 | `SettingsService.pause_campaign` |
| `GET /api/me/notifications` | login | — | 200 `NotificationsOut {items[], unread}`: the caller's own notifications, newest first (`kind` is one of `join_requested`, `join_approved`, `join_rejected`, `drafts_ready`, `hot_lead`, `needs_attention`, `auto_approved`, `run_finished`, `run_failed`, `discovery_paused`, `account`; `data` holds the counts, ids and the workspace's `slug` and `workspace_name`) | — | `IdentityService.notifications` |
| `POST /api/me/notifications/read` | login + CSRF | `ReadIn {id \| null}` (null: all) | 204 | — | `IdentityService.mark_notifications_read` |
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
