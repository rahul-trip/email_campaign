# Phase 6 build progress

A running note of what is built and what is left, updated with every commit. The phase documents say what each step must do; this file says where the build stands. Last updated: 2026-10-26.

Branches (each built on the one before): `phase-6/tenancy-foundation` (6a) → `phase-6/identity-and-access` (6b) → `phase-6/onboarding-and-mailboxes` (6c) → `phase-6/plans-limits-admin` (6d, then 4a and 6g on the same line of work). Nothing has been pushed unless noted.

## 6a, 6b, 6c — code complete

Gates still open, none of them code: database roles in Supabase and a rehearsal on a production copy (6a); a transactional email provider and a deploy (6b); live checks with real Microsoft 365, Google and IMAP mailboxes, plus Google and Microsoft app verification (6c).

## 6d — plans, limits and the admin console

**Done**
- 6d.1 schema (0012), 6d.2 entitlements and once-per-lead charging, 6d.3 waiting and resuming, 6d.5 admin API, 6d.7 customer screens.
- 6d.4 vendor keys in the database (0013): encrypted, versioned, masked, audited reveal, rollback, pause, hot reload in the worker, `vendors import-env`, and monthly spend caps that pause a vendor.
- 6d.6 admin console: Overview, Customers, Customer detail, Users, Plans, Vendors and keys, Settings, Audit log.
- 6d.8 notices: 80% and 100% of a step, access ending and ended, credits granted (to workspace admins); credit requests and vendors paused by their cap (to platform staff). Sent once each, by the worker's periodic pass.

**Left**
- *Test a key* in the console (a real call to each vendor). Needs live keys.
- A notice when a vendor key is *failing* (only "paused by cap" exists).
- Members tab actions on the customer page (role, remove, resend invite, force reconnect). Workspace admins already do these in Team.
- Browser tests of: a free customer's 6th manual lead waits and the admin's grant resumes it; extending access reopens a read-only workspace; the superadmin opens a workspace read-only. The same flows are tested on the API.
- Admin tour section in `web2/src/tour/steps.ts` (the targets `admin-*` are placed).
- Gate record: two pilot customers, and recorded spend against vendor invoices within ±5%.

## 4a — opt-outs and hard bounces

**Done:** rule classifier, `InboxSync` tick job, opt-out and hard-bounce handlers, tests on fixture mailboxes (SQLite and Postgres).

**Left:** a live-mailbox check of both cases (the 4a gate). Everything else in Phase 4 is after the alpha: the model classifier, positive, question, referral and out-of-office handling, soft-bounce retry, follow-ups, the reply webhook and the Replies screen.

## 6g — verified lead directory

Not started. See `phase-6g-lead-directory.md`.

## After the alpha

6e billing, 6f launch readiness, and the rest of Phase 4 and Phase 5.
