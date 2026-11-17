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

## Owners, platform invitations and join requests (2026-10-28, 6h)

Branch `phase-6/owners-and-join-requests`, migration 0017. There is no separate owner role: a workspace's creator is an admin, and any admin decides requests.

Built:
- Platform admins invite someone to Outbound with no workspace (`/api/admin/invitations`, a card on the console's Users page; the token has no workspace).
- After accepting, the person makes a workspace (`POST /api/me/workspaces`, they become its admin) or asks to join one with its **join code** (`POST /api/me/join-requests`, a random 8-character code on `workspaces`, not the slug; 10 wrong codes an hour; an admin can replace it).
- Admins are notified in the app (the bell, `notifications` table) and decide under Settings → Team (`/api/team/join-requests/{id}/approve|reject`, choosing member or admin). The requester is notified and, once approved, the workspace opens.

**Left:** an email to admins about a new request (only the bell today); transferring or sharing the creator's role is just making another admin; a person cannot cancel their own request; no limit on how many workspaces one person may create.

## Discovery and qualification (2026-11-06)

Branches `phase-6/discovery-brief` (migration 0018), `phase-6/discovery-sources` (migration 0019) and the later ones in the plan. Discovery used to make one web search and add every new domain as a lead, scoring fit only after full research. It now works from a brief and screens before adding ([ADR 0031](../technical/adr/0031-multi-source-discovery-screened-before-intake.md)).

Built:
- **The brief.** Each campaign has an editable ideal-customer brief (`campaigns.icp_brief`). A model drafts it from the campaign and the sender profile, and the operator edits it on the Campaigns page under **Who we look for**.
- **Sources.** Discovery looks in the Y Combinator directory (a public mirror, free) when the brief is after start-ups. It also searches for pages that list many companies like the wanted ones and reads them with a model.
- **Screening.** Everything found is merged, screened against the brief in batches, and only fits become leads. Every company is kept with its verdict (`discovery_candidates`) and shown on the run's page, and **Make a lead** promotes one.
- **Qualification** (`phase-6/discovery-qualification`). Research judges each lead against the brief criterion by criterion, with evidence and source, why now and risks; the score is computed in code (`outbound/domain/qualification.py`) and the breakdown is shown on the lead page. A discovered lead whose own site meets a disqualifier stops after the site read.

- **More sources and their record** (`phase-6/discovery-more-sources`). Companies House advanced search (UK briefs with SIC codes) and Exa (company search and lookalikes of example customers and qualified leads, behind `EXA_API_KEY`) are discovery sources. Each source's 90-day record (named, leads, passed the fit gate) orders the sources and sizes their share, and Reports shows it as *Where good leads come from*.

**Left:**
- People Data Labs company search (optional in the plan; not built).
- Live checks of Exa and Companies House advanced search ([R-30](../technical/tech-debt-and-risks.md)).
- Minor findings from the final review, deferred:
  - **Make a lead** with no manual credit says "not added" though the row is queued (a second click queues a duplicate).
  - Intake races are stored as *Does not fit* instead of *A lead already* / *waiting for the next run*.
  - Website searches per run are not capped.
  - Screening's fallback to word matching when the model fails is not logged as a warning.
  - Usable model values are dropped: a score of `72.0`, a founded year as text, and ids like `m1`.
  - Exa `find` ignores `limit` and drops example sites given with `https://`.
  - One malformed Exa or Companies House item can fail that source.
  - Source records count not-yet-researched leads as misses.
  - Search URLs are unfenced in the extract prompt, and the evidence link isn't checked to be `http(s)`.
  - The run page's per-search new/already lead counts are always 0, and a candidate's lead link breaks after the lead is deleted.
  - `Discovery` lacks `screened` and per-source counts.
- A live run against real keys to check that the YC mirror is fresh and that the planned searches read as intended.

## Lead quality (2026-11-16)

Found by reading the VM's worker log and database (read-only) and written up as a plan of small branches, each branched from the one before where they touch the same code. Done: `phase-6/model-reply-budget` (migration 0020, R-35): discovery's model calls are no longer cut off, and a company the model could not judge is kept for the next run instead of rejected. Done on `phase-6/directory-sources` (R-36, stacked on that branch): the Y Combinator directory matches by word and stem and no longer returns 0, and neither it nor Exa repeats companies found before. Done on `phase-6/funnel-report`: `outbound report funnel`, `GET /api/reports/funnel` and a Reports card (the baseline for everything below). Done on `phase-6/brief-and-scoring` (R-37): a brief with no must-haves is judged by its summary, type and size; thin briefs and non-job titles are flagged and a thin brief is drafted once more. The first four branches are merged (#47 to #50). Done on `phase-6/lead-quality-part-2`, one PR for the rest: emails go only to decision-makers or people the operator chose, research follows the site's team links and searches for people when the site names no decision-maker (R-38, closes R-21); Scrubby uses its real deep-verification endpoints and a resolver outage is a failure to retry, not a verdict (R-39); the copy reading-grade limit is 12 (R-40). After deploy: press *Find email again* on the leads held for a catch-all; Enrichley answers 403 to its key and needs the account checked.

## Operator experience (2026-11-16, migrations 0021–0023)

Done, on branch `phase-6/operator-experience` (one commit per point): the Runs form loses "Leads per stage" (and a queued run keeps `skip_directory`, R-41); Needs attention gets **Find email again** for catch-all holds, per lead and for all; the lead, run and report pages use collapsible cards, closed by default; each vendor call records what it asked and got (`provider_calls.detail`); the lead's timeline becomes **Activity**; one active campaign per workspace, a paused campaign's leads wait, and a workspace without a ready active campaign sees a "Create your campaign" gate; hot (above 80) and cold leads, with the optional automatic approval of cold drafts (off by default, [ADR 0033](../technical/adr/0033-cold-drafts-may-be-approved-without-a-person.md)); automatic discovery about four times a day and stopped while Review holds 50 drafts; the bell reports what runs and leads did.

Not checked live: nothing here has been deployed or run against the real vendors. Open: a migration test for the "keep the campaign with the most leads" rule (0022); the Journey page does not show the new "what was asked" text yet (its API carries it); only Review sorts hot leads first.

## Account deletion (2026-11-17, branch `phase-6/delete-account`)

Done: a person deletes their own account (Settings → Your account, password required) and a superadmin deletes any account (console → Users). Hard delete; mailboxes disconnected; a sole member's workspace suspended; the last admin of a shared workspace and the last superadmin are refused. No migration. Not checked live: a Google mailbox's grant revocation on delete. Open: no purge of a suspended workspace left behind.

## People placement (2026-11-17, branch `phase-6/people-placement`, migration 0025, R-42)

Done: every person a search finds is placed at the company by rules (`domain/placement.py`) and, for the unsure, one model call per lead; people who work elsewhere are kept as `not_here`, never worked on and not added again; the lead page shows why, can set someone aside or bring them back, and **Check who works here** re-checks a lead's people. Not checked live: the model's verdicts on real profiles; run `check-people` on `quantra-energy-2` after deploy and read the result before trusting it on every lead. Open: no script yet to re-check every lead in a workspace at once.

## LinkedIn messages (2026-11-17, branch `phase-6/people-placement`, migration 0026, R-43)

Done: the contacts step writes a connection note and a follow-up for each confirmed decision-maker with a LinkedIn profile, before any email is looked for; the lead page has a LinkedIn card and the nav a LinkedIn page (copy, edit, rewrite, skip, mark sent); marking one sent holds the lead's email as `linkedin_contacted`, released to the email step, and the email then mentions it. Nothing is sent to LinkedIn. Not checked live: draft quality on real research. Open: setting someone aside as not here does not skip their unsent draft (R-43); the 200-character limit is not a setting.

## Fewer vendor and model calls (2026-11-17, same branch)

Done: LinkedIn profile lookups in research ask for five people per search (a lead with ten people: 2 searches, was 10); **Check who works here** reads profile headlines five people per search (was one each); LinkedIn drafts for a lead's people are one model call (was one per person, up to three), with one more call only for the drafts the checks reject. Related questions now share one model call with one output schema: the site call also returns the people on the team pages (given in their own block with their own length cap, so nothing is cut short or sent twice), and the news call also answers the campaign's questions and the hiring and tech signals. Research makes 3 model calls instead of 5 for a typical lead.

## After the alpha

6e billing, 6f launch readiness, and the rest of Phase 4 and Phase 5.

## web3 redesign (2026-11-17, branch `phase-6/web3-redesign`)

- A new web app in `web3/` beside web2 (kept as it is), over the same API and data; no migration.
- Read-only API additions for it: lead filters (`min_fit`, `hot`, `source`, `country`), `sort` and `include=summary` on `GET /api/companies`; `GET /api/reports/daily`, `GET /api/reports/fit`, `GET /api/runs/plan`. Tests in `tests/api/test_web3_reads.py`.
- Route parity with web2 is checked in CI (`npm run check:parity`); all 181 routes are covered.
- `WEB_APP` picks the app; the default is web3.
- Guided tour and the full browser suite run on web3 (40 tests, in CI). The admin console has its own staff header. The user manual describes web3 (§5a).
- **web3 is the app (2026-11-17).** The Docker image builds web3 and `WEB_APP` defaults to it (image build checked locally); CI tests web3 only; web2 stays in the repo, unused. The tour is nine short steps. The shared component layer was restyled, so every screen matches. Left: deploy to the VM and look at it with real data (no `WEB_APP` change needed).
