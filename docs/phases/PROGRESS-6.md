# Phase 6 build progress

A running note of what is built and what is left, updated with every commit. The phase documents say what each step must do; this file says where the build stands. Last updated: 2026-10-26.

Branches (each built on the one before): `phase-6/tenancy-foundation` (6a) → `phase-6/identity-and-access` (6b) → `phase-6/onboarding-and-mailboxes` (6c) → `phase-6/plans-limits-admin` (6d, then 4a and 6g on the same line of work). Nothing has been pushed unless noted.

## 6a, 6b, 6c — code complete

Gates still open, none of them code: database roles in Supabase and a rehearsal on a production copy (6a); a transactional email provider and a deploy (6b); live checks with real Microsoft 365, Google and IMAP mailboxes, plus Google and Microsoft app verification (6c).

## 6d — plans, limits and the admin console

**Done**
- Browser tests (`web2/e2e/credits.spec.ts`): a customer over its allowance waits and the admin's grant in the console adds the lead; a superadmin opens a workspace read-only. Members tab (role, remove) and Force reconnect on a mailbox, both audited.
- 6d.1 schema (0012), 6d.2 entitlements and once-per-lead charging, 6d.3 waiting and resuming, 6d.5 admin API, 6d.7 customer screens.
- 6d.4 vendor keys in the database (0013): encrypted, versioned, masked, audited reveal, rollback, pause, hot reload in the worker, `vendors import-env`, and monthly spend caps that pause a vendor.
- 6d.6 admin console: Overview, Customers, Customer detail, Users, Plans, Vendors and keys, Settings, Audit log.
- 6d.8 notices: 80% and 100% of a step, access ending and ended, credits granted (to workspace admins); credit requests and vendors paused by their cap (to platform staff). Sent once each, by the worker's periodic pass.

**Left**
- *Test a key* has no cheap check for Scrubby and Enrichley (the catch-all resolvers); they are tested by first use. The tests use fakes, so the real calls still need a live check.
- A browser test of "extending access reopens a read-only workspace" (the API test exists; the e2e server cannot start a workspace past its access date).
- An admin tour section (the console has no tour yet; the `data-tour` targets are in place).
- Resending a customer's pending invitation from the console (the customer's own admins can do it in Team).
- Gate record: two pilot customers, and recorded spend against vendor invoices within ±5%.

## 4a — opt-outs and hard bounces

**Done:** rule classifier, `InboxSync` tick job, opt-out and hard-bounce handlers, tests on fixture mailboxes (SQLite and Postgres).

**Left:** a live-mailbox check of both cases (the 4a gate). Everything else in Phase 4 is after the alpha: the model classifier, positive, question, referral and out-of-office handling, soft-bounce retry, follow-ups, the reply webhook and the Replies screen.

## 6g — verified lead directory

**Done** (migration 0014, tests on SQLite and Postgres):
- Platform tables for companies, people, addresses, observations, reports and removals; the app role can read served facts only, insert observations, reports and removals, and cannot read who contributed or reported (a Postgres privilege test).
- Rules (`domain/directory.py`), repositories (`db/repositories/directory.py`), `DirectoryFinder` first in the waterfall at price 0 with a ledger row per lookup, contributions from the email stage, the directory's email pattern when a company has none.
- Skip the directory per lead, only with the `directory_bypass` ability (refused on the server otherwise).
- Reports stop an address being served at once; staff accept or reject them; an accepted one is never learned again.
- Forgetting a person clears their observations and reports, removes them from the directory and blocks adding them again; facts expire after 24 months.
- A periodic pass folds observations (`DirectoryService.run`, in the worker).
- Admin "Lead directory" screen (size, hits and savings this month, reports to decide, history of one fact) and the lead page card (badge by month, report, skip).
- A report on an address or "no longer works there" also marks the address invalid in the reporting workspace.
- The public "Remove my data" page with an emailed confirmation (migration 0015), and `outbound directory backfill --since DATE [--apply]`.
- The gate test: a person verified for one customer costs the next no finder call (`tests/db/test_pipeline_e2e.py`).

**Left:**
- Reconfirmation by a verifier or search, on a button and on a schedule, metered to an internal `directory` workspace. Today staff accept or reject a report by hand and nothing is re-verified on a timer.
- Contributions of people and companies beyond addresses and patterns: titles are kept, but LinkedIn profiles, legal entity and registry numbers are not contributed.
- The opt-in setting for operator-typed contacts has no screen (the key `directory_share_operator_contacts` is read, default off).
- Hard bounces and "no longer works here" replies disputing facts automatically (4a suppresses the address in the workspace only).
- Accuracy per source and reporters' track record on the admin screen; down-weighting repeat false reporters.
- Hashed removals by LinkedIn URL or by name and domain (only addresses are hashed).
- The legal checklist before the public launch (6f).

## Left points worked on (2026-10-28)

Built: the console's **Test** button per vendor (one small real call with the stored key), a *key refused* flag and a once-a-day staff email when a vendor rejects our key three times in a day, and the run-level "find emails with the vendors" option. **Decided not to build** the lead page's *Reconfirm* button: every address the directory serves is already checked by the verifier before it is used, so a second button would repeat that check.

## Follow-up changes after the PR (2026-10-27)

Small changes asked for while testing, on branch `phase-6/lead-page-and-profile-upload`: LinkedIn lookup for every person (automatic for ten per lead in research, plus a button), **Find email again** per person (migration 0016), research no longer limited or cut short and shown in sections, the whole sender profile from a downloadable JSON file, timestamps and an email history on Review and across the lead pages, the intake webhook's request body and an example, and staff browsing, adding, editing and removing directory entries and company patterns. The manual and tour are updated.

## After the alpha

6e billing, 6f launch readiness, and the rest of Phase 4 and Phase 5.
