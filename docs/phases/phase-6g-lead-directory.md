# Phase 6g — Verified lead directory

**Goal:** one shared source of truth for verified business facts, built up from every customer's runs:
- companies, people and their LinkedIn profiles, and work emails;
- checked before any paid vendor is called;
- correctable by customers when a detail is wrong.

**Depends on:** 6d (platform tables, the admin console, the skip toggle). It starts after the alpha begins, in parallel with Phase 4; the alpha does not wait for it.

**Gate:**
- **Free first link:** a lead whose person was already verified for another customer gets its email from the directory, with no paid finder call.
- **Skipping:** with the skip option, the vendors are called, and their results update the directory.
- **Reports:** a reported fact is not served until it is reconfirmed.
- **Privacy:**
  - no response contains a contributor, a reporter, a first-seen date or a lookup date;
  - the app role cannot read contributors or reporters (a privilege test).
- **Erasure:** forgetting a person removes them from the directory and blocks re-adding.
- **Reporting:** the admin Directory screen shows the hit rate and the money saved.

## Decisions

- **Everything verified is shareable:** companies, people and emails, including addresses Hunter found.
  - This is the alpha's decision.
  - Hunter's content policy restricts redistributing its individual-level data, so that risk was accepted for the alpha and is revisited before the public launch (6f).
  - Every fact keeps its source, so a filter by source can be added later.
- **Customers may skip the directory** for a run or a lead and go straight to the vendors, when an admin has turned on `directory_bypass` for them (6d, Access & features).
- **Contacts typed in by an operator** (an address from a business card, for example) enter the directory only when the workspace opts in. Off by default.
- **Inside a workspace, the operator's input still wins** (CLAUDE.md rule 7). A customer's correction fixes its own record at once and becomes a report to the directory; it never overwrites the directory directly.

## What is in it, and what never is

**In it:**
- **Companies:** domain, name, country, legal entity, registry number, LinkedIn page, email pattern and its confidence, catch-all status, mail provider.
- **People:** name, title, LinkedIn profile, whether they still work there.
- **Emails:** address, verification status and date, provenance, source.

**Never in it:**
- notes, campaigns, fit scores, research answers;
- messages, replies, consents and their evidence, suppressions;
- operator-typed contacts, unless the workspace opts in;
- any trace of who looked up or prospected whom.

## How it works

1. **Facts come only from verified results.** A stage returns observations in its `StageResult`, and the runner writes them in its one short transaction. An observation is one of:
   - an address a verifier returned as `valid` or `catch_all_resolved`;
   - a person confirmed by the employer-match rule (Phase 3b.13);
   - a company identified from its own site or from Companies House.
2. **A platform job folds the observations into served facts.** `directory_observations` is append-only, and each fact keeps its source and time.
3. **The email waterfall gets a free first link.** `DirectoryFinder` implements the `EmailFinder` port (`providers/ports.py:47`) and is placed first in the `Waterfall` (`stages/email/waterfall.py:90`).
   - It serves an address only when it is verified, fresh (verified within 90 days) and undisputed.
   - A stale address gets one re-verification (about $0.0002–0.008) instead of a finder lookup (about $0.16; [../PLAN.md](../PLAN.md) §12). The result goes back into the directory.
   - It goes through the Meter at price 0 with no cache, so every hit and miss is a `provider_calls` row with `provider = "directory"`. That gives the hit rate and the savings.
4. **Domain patterns.** When the workspace's company has no `email_pattern`, the email stage takes the directory's verified pattern. It builds one address and verifies it instead of calling a finder. A pattern is an aggregate fact, not personal data.
5. **Skipping.** With the ability on, the run option or the lead action **Find email with vendors** sets `skip_directory`.
   - The waterfall leaves out `DirectoryFinder` and the directory's patterns.
   - Without the ability, the option is hidden and the server refuses it.
6. **Reports.** **Report wrong detail** works per field: email, title, still works there, LinkedIn, company name or country.
   - It corrects the customer's own record at once.
   - It adds a row to `directory_flags`.
   - It marks the fact *disputed*, so it is not served until reconfirmed.
7. **Reconfirmation** comes from a button on the lead page, staff on the Directory screen, or a scheduled job:
   - an email by a verifier;
   - a person by one search;
   - a company by its site or the registry.

   Scheduled reconfirmation is metered to the platform's internal `directory` workspace, so its cost shows on its own.
8. **Automatic signals:**
   - hard bounces and "no longer works here" replies (Phase 4) dispute facts;
   - facts not reconfirmed within 24 months are deleted.
9. **Against poisoning:**
   - one report disputes a fact but never deletes it;
   - reporters whose reports keep being rejected are down-weighted, which only staff can see.
10. **Provenance travels with an address.** The `allowed_provenance` rule for Canada (CASL) still applies to an address that came from the directory.

## Privacy and isolation

- **Platform tables.** The app role may:
  - SELECT the served facts (`directory_companies`, `directory_people`, `directory_emails`);
  - INSERT observations and reports.

  Contributor and reporter columns are readable only by `outbound_platform`, enforced with column privileges and a separate table.
- **No side channels:**
  - customers never see first-seen or last-looked-up dates;
  - verification dates are shown by month only, so a hit never reveals that someone else is prospecting the same person.
- **Erasure:**
  - forget in any workspace also removes the person from the directory, and adds a hashed `directory_suppressions` entry so they are never re-added;
  - a public "Remove my data" page serves people directly.
- **A platform switch** turns cross-customer serving off at once, if counsel asks for it.

## Tasks

### 6g.1 Migration 0013

- [ ] `directory_companies`: `domain` (unique), `name`, `country_code`, `legal_entity_type`, `registry_number`, `linkedin_url`, `email_pattern`, `pattern_confidence`, `catch_all`, `mail_provider`, `status`, `last_confirmed_at`.
- [ ] `directory_people`: `company_domain`, `full_name`, `first_name`, `last_name`, `title`, `seniority`, `linkedin_url` (unique where not null), `employment_status` (`current`, `left`, `unknown`), `status`, `last_confirmed_at`.
- [ ] `directory_emails`: `email` (unique), `person_id`, `status`, `provenance`, `source`, `verified_by`, `verified_at`.
- [ ] `directory_observations`: append-only; `target_type`, `target_key`, `field`, `value`, `source`, `observed_at`, and `contributor_workspace_id` (platform-only).
- [ ] `directory_flags`: `target`, `field`, `reason`, `status` (`open`, `confirmed`, `rejected`), `resolution`, `resolved_at`, and `reporter` (platform-only).
- [ ] `directory_suppressions`: hashed email, LinkedIn URL, or name plus domain.
- [ ] Grants and column privileges as above. [../SCHEMA.md](../SCHEMA.md) is updated in the same PR.

### 6g.2 Rules

- [ ] `outbound/domain/directory.py` holds:
  - what may be served: freshness, disputes, status;
  - how observations fold into a fact;
  - the retention window;
  - the `DirectoryReader` protocol.

  No I/O.

### 6g.3 Repository and jobs

- [ ] `outbound/db/repositories/directory.py`: served reads and observation inserts for the app role; folding and reconfirmation queues for the platform role.
- [ ] Platform jobs in the tick:
  - fold new observations into facts;
  - schedule reconfirmation of stale facts;
  - delete facts past retention.

### 6g.4 The free first link

- [ ] `DirectoryFinder` in `stages/email/`, first in the waterfall, wrapped by the Meter at price 0 with no cache.
- [ ] The directory's pattern is used when the workspace has none (`stages/email/stage.py:146` learns patterns today).
- [ ] `skip_directory` is a run parameter and a lead action, checked on the server against `directory_bypass`.

### 6g.5 Observations from the stages

- [ ] `StageResult` carries observations. Research contributes companies and confirmed people; email contributes verified addresses and patterns; Phase 4 contributes bounces and "left the company".
- [ ] Operator-typed contacts are contributed only when the workspace opts in.

### 6g.6 Reports and reconfirmation

- [ ] **Lead page:**
  - a "verified · month · source" badge on each directory-backed fact;
  - **Report wrong detail**;
  - **Reconfirm**: metered to the lead, and refused once the lead's budget is used up.
- [ ] **Admin, the Directory screen:**
  - size and freshness;
  - hit rate and money saved by month;
  - open reports, with **Reconfirm now**, **Accept correction** and **Reject**;
  - the reconfirmation queue;
  - accuracy per source (whose addresses bounce);
  - reporters' track record;
  - a search for one fact by domain or email, showing its observation history.

### 6g.7 Erasure and removal

- [ ] `services/forget.py` also removes the person from the directory and writes the hashed suppression. The existing column-scan test is extended to the directory tables.
- [ ] A public "Remove my data" page, outside the app shell. It sends an email confirmation link, and the removal is recorded in the audit log.

### 6g.8 Backfill

- [ ] A one-off command, with a dry run first, loads the verified facts recorded since the alpha began. The Terms and DPA agreed at sign-up (6c) cover this.

## Before the public launch (6f): legal checklist

Keeping the directory makes the platform its **controller**, not only the customers' processor, and probably a **data broker** under some US laws. Each item needs counsel's sign-off:

- [ ] A legitimate-interests assessment and a DPIA.
- [ ] **GDPR Art. 14 notices to each person** within a month of collection. Poland's regulator fined Bisnode about €220k (2019) for relying on a website notice instead.
- [ ] US data-broker registration where it applies. California's DROP deletion requests must be processed at least every 45 days from 1 August 2026.
- [ ] Each vendor's terms checked, Hunter's first, and source filters added if needed.

## Tests that must exist

- **Finder order:** freshness, disputes and re-verification; `skip_directory` honoured and refused without the ability.
- **Folding and serving:** observations fold correctly, and only verified facts are served.
- **Reports:** a report stops serving; reconfirmation restores or corrects the fact.
- **Privacy:**
  - the app role cannot read contributor or reporter columns (Postgres privileges);
  - responses carry month-only dates and no lookup data.
- **Erasure:** forget removes the person and blocks re-adding; the column scan covers the directory.
- **Provenance:** it is kept, and the Canadian rule still applies.
- **The ledger:** zero-cost rows; hit-rate and savings figures.

## Gate record

- Date:
- Hit rate and savings in the first month:
- Privacy and privilege tests:
- Checked by:
