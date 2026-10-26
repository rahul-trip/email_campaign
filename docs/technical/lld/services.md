---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Services

**Code:** `outbound/services/` · **Layer:** services (above runner; below pipeline and the entry points) · **Tests:** `tests/db/` (one or more files per service), `tests/api/`, `tests/test_cli.py`

## Purpose

Services are the operator's use cases: add targets, review an email, edit a lead, skip a check, forget a person, change a setting, read a report. The CLI and the API share them, so a rule (such as "approval needs an acknowledgement for skipped checks") is enforced the same way whichever door the operator uses. This is where operator actions become transitions and events.

## Responsibilities

- Validate the operator's request and refuse what is not allowed, with a message that says what to do.
- Make the change in one unit of work, through repositories, writing the events.
- Do outside work (searches, deleting drafts) before or after the transaction, never inside it.

**Not their job:**

- parsing HTTP or the command line ([API](api.md), [CLI](cli.md));
- running the pipeline ([runner](runner-and-worker.md));
- the rules themselves ([domain](domain.md)).

## The services

| Module | Main symbols | Used by |
|---|---|---|
| `intake.py` | `IntakeService` (`run`, `needing_confirmation`, `confirm`), `DomainResolver`, `match_confidence`, `discover_rows`, `discovery_query`, `load_rows`, `parse_target` | CLI `targets`, `run --mode discovery\|mixed`; API targets router; webhook; `pipeline.discover_companies` |
| `review.py` | `ReviewService` (`queue`, `resolve`, `show`, `approve`, `reject`), `ReviewError`, `footer_of` | CLI `review`; API review router |
| `leads.py` | `LeadService` (below), `LeadError` | API leads, targets and privacy routers; data-fix scripts |
| `privacy.py` | `PrivacyService` (`forget`, `suppress_contact`, `suppress_company`, `suppress_value`, `delete_lead`) | CLI `forget`, `suppress`, `delete-lead`; API privacy router |
| `forget.py` | `forget_email`, `stop_contact`, `suppress_if_nobody_left` | `PrivacyService` (runs inside the caller's unit of work) |
| `settings.py` | `SettingsService` (sender profile, workspace settings, campaigns, policies, suppressions, mailboxes, `dns_check`), `SettingsError` | API settings router; CLI `sender-profile` |
| `runs.py` | `RunService` (`queue`, `get`, `recent`, `cancel`), `RunRequest`, `RunMode` (`manual`, `discovery`, `mixed`) | API runs router; worker (`RunRequest.from_params`) |
| `reports.py` | `ReportService` (`status`, `quality`, `cost`) | CLI `status`, `report`; API runs router |
| `journey.py` | `build_journey` (pure), `Journey`, `StageView` | `LeadService.journey` |
| `webhook.py` | `WebhookService.receive`, `sign`, `verify` | API webhook router |
| `seed.py` | `seed_defaults` | CLI `seed` (and the `migrate` service on every deploy) |
| `defaults.py` | `default_sender_profile`, `default_workspace_settings` | `seed`, `SettingsService` |
| `dns_check.py` | `check_domain`, `system_lookup` | `SettingsService.dns_check` |
| `legacy_import.py` | `import_legacy_xlsx` | CLI `import-legacy-xlsx` (one-time, idempotent) |

## Intake

`IntakeService.run(rows, source, company_source, campaign_id, filename, validate_only)`:

1. **Parse** each row into a `Target` and detect its anchor (`detect_anchor`): domain or website, company name, email, person and company, or LinkedIn URL.
2. **Resolve before the transaction.** Rows without a domain are looked up by name with one metered search each (`DomainResolver.by_name`). LinkedIn rows are looked up by the profile slug (`by_linkedin`). `match_confidence` scores a site with no model involved:

   | Match | Confidence |
   |---|---|
   | The site's name is the whole company name (`acmeenergy.com` for Acme Energy) | 0.95 |
   | The site's name contains it (`acmeenergy.com` for Acme) | 0.85 |
   | All the name's words appear in the hit's title and snippet | 0.65 |
   | Otherwise | 0.4 |

   **Below 0.8, the row waits as `needs_confirmation`** for the operator (`confirm(row_id, domain)`). The parent group's site (`tata.com` for Tata Power) falls below the threshold.
3. **One transaction for the batch.** Create the batch. For each row, `_decide` rejects it if:
   - its domain or email is suppressed;
   - it uses a free-mail address without `allow_personal_domain`;
   - it points at a platform domain.

   Otherwise it creates the company, or **merges** into an existing one with the same registrable domain: notes are appended, and differing values become events rather than overwrites. An operator-given person or address becomes an `active` contact, and an `operator_given` address. Each row is recorded with its status, resolved domain, confidence and reason.
4. With `validate_only`, no search is made and the transaction is rolled back.

**Discovery** (`discover_rows`):

1. `discovery_query` phrases the campaign's ideal customer as a search for *companies offering* it.
2. It asks for twice the wanted count.
3. It skips platforms, free-mail domains, articles and documents (by path), and duplicates.
4. Each row holds **only the website**, plus a note with the page it was found on, never the hit's title ([ADR 0023](../adr/0023-discovery-stores-websites-unconfirmed-people.md)).

## Review

- `queue()` lists `generated` step-0 messages with their lead, contact, address, lint flag and skips.
- `resolve(ref)` accepts a short id prefix and refuses an ambiguous one.
- `approve(message_id, edited_body, expected_version, acknowledge_skips)`, in one transaction:
  1. Refuses if the message changed since it was opened (`ConcurrencyConflict`).
  2. Refuses if the address or its domain is now suppressed.
  3. Refuses if the email relies on skips (`_skips`: `country_policy`, `email_verification`, `works_here`) without `acknowledge_skips`.
  4. If edited:
     - refuses an edit that removed the footer (`_check_footer`);
     - stores `final_body` and `edit_distance`;
     - writes `edited`.
  5. Moves the message to `approved`.
  6. Writes `approved_with_skips` with the kinds, if there were skips.
  7. Moves the company to `approved`.
- `reject(message_id, reason)` requires a reason. It moves the message and the company to `rejected`, which is final, and writes `rejected` with the reason.

See [safety model §5](../hld/safety-model.md#5-human-approval).

## Leads

Every write goes through `LeadService` and writes events. Refusals raise `LeadError` (API `409 action_not_allowed`), or `InvalidInput` (`422`) for bad input.

| Operation | What it does | Refused when |
|---|---|---|
| `search`, `detail`, `timeline`, `journey`, `waterfall` | Read models for the screens | — |
| `update(company_id, changes, expected_version)` | Operator edit of the lead's fields (into `manual_fields`) | Stale version |
| `retry` | `failed` → the failed stage's input status, ignoring the back-off and the attempt limit | Not failed |
| `release_hold(resume_to=None)` | `held` → the hold reason's resume point, or `resume_to` | Not held; `needs_operator` with no `resume_to`; **a country-rule hold whose cause has not changed**, which would only hold it again. The message says how to fix it |
| `requalify` | `disqualified` → `qualified` (operator override of fit) | Not disqualified |
| `add_person(full_name, title, email, consent…)` | Adds an `active` person, or **updates the same person** (`same_person`: case and accents ignored, first name matches full name); optional address (`operator_given`) and consent. Releases a matching hold | A one-word name with no work email (the finders need both names) |
| `update_person` | Edit name or title; a new address is kept beside the old one; retries a failed email step | — |
| `confirm_person` | `unconfirmed` → `candidate` with the reason "confirmed by the operator: works here" | Not unconfirmed |
| `remove_person` | Deletes a wrongly matched person (`ErasureRepository.delete_contact`) | Anything has been written to them |
| `change_recipient(contact_id)` | Cancels the waiting email; the lead goes back to `contacts_found` with that person first | The lead is past the mailbox, or in a status where the recipient cannot change |
| `record_consent` | One active consent per basis per person; the person ranks first | — |
| `skip_policy(from_stage, reason)` | Sets `policy_skip_from`; writes `policy_skip_granted`; a lead the rule stopped resumes where it stopped (`RESUME_AFTER_SKIP`), and a `disqualified` lead goes to `qualified` | No reason; nothing left to check; a start later than where the rule stopped the lead |
| `revoke_policy_skip` | Clears the skip; writes `policy_skip_revoked` | At or after approval |
| `release_policy_holds` | After switching the workspace's rules off, releases every lead held by a country rule | — |
| `skip_email_verification(email_id, reason)` / `restore_email_verification` | Sets or clears `verification_skipped`; a lead failed at email or held on a catch-all goes back to the email step | No reason; a suppressed address; restore after approval |

## Privacy

Mailbox drafts are always deleted **after** the commit. Drafts that cannot be deleted are returned (`drafts_left`) and logged, never silently dropped.

| Operation | Effect |
|---|---|
| `forget(email)` | `forget_email`: suppress the address; cancel unsent messages; contact → `forgotten`, scrubbed; suppress the company if nobody is left; one `forgotten` event |
| `suppress_contact`, `suppress_company`, `suppress_value` | Suppress, cancel unsent messages, delete their drafts. Records are kept |
| `delete_lead(company_id, confirm_domain, also_suppress_domain)` | Typed domain required; refused if any message was `sent` or `bounced`; `ErasureRepository.delete_company`; optional domain suppression; logs `lead_deleted` |

Details: [data lifecycle](../data/data-lifecycle.md#the-three-ways-out).

## Settings

- **Sender profile:** `update_sender_profile` accepts only known fields. Every save counts as a review and sets `reviewed_at` on the server, never from the client. Writes `sender_profile_reviewed` with the field names.
- **Workspace settings:** `update_workspace_settings` accepts only known fields, refuses `send_enabled` before Phase 5, and writes `settings_changed` with the values.
- **Country policies:**
  - `save_policy` creates or edits a rule (the version bumps on a real change) and writes `policy_changed`;
  - `delete_policy` writes `policy_deleted`.
- **Campaigns, suppressions, mailboxes:** create and update. `dns_check` checks SPF, DKIM and DMARC for the mailbox domain through an injectable lookup (tests use no network).

## Runs and reports

- `RunService.queue(RunRequest)` inserts a `queued` run, with `mode`, `limit` (1–500), `discover` (1–50), `campaign` and `only` in `params`.
- `cancel` stops a queued run at once, and asks a running one to stop between leads.
- `get` returns live cost while running.
- **Reports** (`ReportService`, over `ReportRepository`):
  - `status`: counts by status, the review queue, holds;
  - `quality`: unedited share of sent touch-1 emails against the 80 % target, flag rate, holds by reason, catch-all share;
  - `cost`: spend by vendor and per prospect over a window.

## Webhook

`WebhookService.receive(payload)`:

- needs `event_id`;
- takes 1 to 200 targets;
- is idempotent: the batch label is `webhook:<event_id>`, and a duplicate, including one racing in at the same moment and caught as an `IntegrityError`, is answered as such;
- runs intake with source `webhook`.

Signature checking (`verify`) happens in the router before this ([webhook integration](../api/webhook-integration.md)).

## Invariants

- No operator action changes a status except through a repository transition, with an event.
- Every refusal says why, and what to do instead.
- No transaction is open during a search, a DNS lookup or a mailbox call.
- Mailbox drafts are deleted only after the database change has committed.

## Transactions and concurrency

One unit of work per operation. Edits to a lead or a message carry the `row_version` the screen read, so the API answers `409 version_conflict` if something changed. Intake runs its searches first, then writes the whole batch in one transaction.

## Observability

- **Log events:** `intake_search_failed`, `lead_deleted`, `privacy_action`, `draft_delete_failed`.
- **`events` rows:** `intake_accepted`, `intake_merged`, `edited`, `approved_with_skips`, `rejected`, `policy_skip_granted` and `_revoked`, `email_verification_skipped` and `_restored`, `consent_recorded`, `person_removed`, `forgotten`, `suppression_added`, `policy_changed`, `policy_deleted`, `settings_changed`, `sender_profile_reviewed`, `legacy_imported`.

See [observability](../operations/observability.md).

## Security and privacy

- Services are where operator intent is checked server-side ([ADR 0012](../adr/0012-server-side-safety-gates.md)).
- Sender-profile text is free text and is not logged.
- Privacy operations never log an address; `lead_deleted` logs the domain ([R-14](../tech-debt-and-risks.md#r-14--p2--privacy-personal-data-in-logs)).

## Tests

| Service | Files |
|---|---|
| Intake | `tests/db/test_intake.py` |
| Review | `tests/db/test_review_and_deliver.py`, `tests/db/test_verification_skip.py` |
| Leads | `tests/db/test_leads_and_settings.py`, `tests/db/test_policy_skip.py`, `tests/db/test_verification_skip.py` |
| Privacy and forget | `tests/db/test_forget.py`, `tests/db/test_privacy.py`, `tests/db/test_delete_lead.py` |
| Seed, legacy import | `tests/db/test_seed.py`, `tests/db/test_legacy_import.py` |
| Data fix | `tests/db/test_fix_discovery_data.py` |
| Through HTTP and CLI | `tests/api/test_endpoints.py`, `tests/test_cli.py` |

## Known limitations

- `release_policy_holds` and other bulk actions run in one transaction without paging.
- Adding a person to a company through intake merges notes but not new people (Phase 3b C4, partly done through **Add a person**).

## Planned

- Phase 4 adds reply handling and follow-up services: [phase-4-close-the-loop.md](../../phases/phase-4-close-the-loop.md).
- Phase 6 adds users and memberships: [phase-6-saas-ready.md](../../phases/phase-6-saas-ready.md).

## How to refresh this page

```bash
grep -n "^class \|^    def [a-z]\|^def [a-z]" outbound/services/*.py
grep -rn "raise LeadError\|raise ReviewError\|raise SettingsError" outbound/services | wc -l
uv run pytest tests/db -q -k "intake or review or leads or privacy or forget or seed"
```
