---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# API reference

Every operation the API serves: **59 operations on 48 paths**. The machine-readable contract is `web2/openapi.json`. It is generated from the app, and it is the source the web client's types come from. Request and response models are summarised here; their full shape is in that document. Authentication, CSRF, errors and concurrency rules are in [API conventions](api-conventions.md), and they apply to every row below.

**Auth column:**

- **open:** no login;
- **login:** the session cookie;
- **login + CSRF:** the session cookie, plus `X-Requested-With` on writes;
- **HMAC:** a signed request, see [webhook integration](webhook-integration.md).

**Common errors** apply to every authenticated operation and are not repeated in the rows:

- `401 unauthenticated`;
- `403 missing_header` on writes;
- `422 validation_failed` for a malformed body;
- `404 not_found` for an id that does not exist in this workspace;
- `500 internal_error`.

The "Errors" column lists only the ones specific to that operation.

## Auth

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/auth/login` | CSRF | `LoginIn {password}` | 200 `Me`; sets the `outbound_session` cookie | 401 `bad_credentials`, 429 `too_many_attempts` | `Sessions`, `LoginThrottle` |
| `POST /api/auth/logout` | CSRF | — | 204; clears the cookie | — | — |
| `GET /api/auth/me` | login | — | 200 `Me` | 401 when signed out (the client's way to find out) | — |

## Intake webhook

| Method and path | Auth | Request | Response | Errors | Calls |
|---|---|---|---|---|---|
| `POST /api/intake/webhook` | HMAC (`X-Signature`, `X-Timestamp`) | Raw JSON, ≤ 1 MB: `event_id`, `targets` (1–200) | 200 object (accepted and duplicate counts) | 401 `bad_signature`, `stale_timestamp`; 413 `body_too_large`; 422 `bad_json`, `missing_event_id`, `bad_targets`; 503 `webhook_disabled` | `WebhookService.receive` |

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
