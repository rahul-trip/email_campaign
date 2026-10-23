# Phase 3b — Hardening before live use

**Goal:** close the gaps found after Phases 0–3 were built, so the engine can be used on real prospects without silent failures, compliance risks or dead ends for the operator.
**Depends on:** Phases 0–3 (code complete).
**Comes before:** Phase 4. Nothing here adds Phase 4 scope (follow-ups, reply triage, sending).
**Status (2026-10-18):** planned. Found by an audit of the code, the user manual, and the first live test run.

**Gate:**
- Every gap marked **P0** is fixed, with tests.
- The operator can resolve every hold reason and every failure from the web app, without the API or a database tool. Each row of the manual's "Known limits" is either gone or moved to Phase 4 on purpose.
- One live run on 5 real targets goes from intake to a draft in the mailbox, with the mailbox, Companies House and the finder chain live.

---

## 1. How the gaps were found

1. **Comparing the plan with the code.** Every promise in [PLAN.md](../PLAN.md) and the Phase 2 and 3 documents was checked against what exists.
2. **Writing the user manual.** Every place where the honest answer was "you can't do that yet" became a gap.
3. **The first live run** (Open Climate Fix and WattTime, 2026-10-18), plus reading the cached vendor answers it produced.
4. **Reading the code paths** for each status, hold and failure, to see where a lead can get stuck.

## 2. Priorities

| Priority | Meaning |
|---|---|
| **P0** | Must be fixed before any real email is sent. A legal, data-loss or correctness risk |
| **P1** | Must be fixed before routine weekly use. Without it the operator gets stuck or work is wasted |
| **P2** | Should be fixed soon. Quality, clarity or cost |

Effort is rough: **S** is under half a day, **M** one to two days, **L** three days or more.

## 3. The gaps

### A. Safety and compliance

| ID | Gap | Evidence | Risk | Fix | Pri | Effort |
|---|---|---|---|---|---|---|
| A1 | **The seeded sender profile contains specific claims** ("reduced forecast error 30% for a UK energy trader: GBP 2M annual P&L uplift") copied from the legacy examples. The writer uses them as proof. The first live email quoted one | `services/defaults.py`; live email to WattTime | A false claim in a real email | Seed value propositions and proof points empty. Add `sender_profile.reviewed_at`; the copy stage refuses until the operator has saved the profile once (`StageFailure` "review your sender profile"). Settings shows a banner until then | P0 | S |
| A2 | **A UK company counts as incorporated if "Ltd", "Limited", "LLP" or "PLC" appears anywhere in its pages**, even naming a partner or client | `stages/research/facts.py::find_incorporation_markers` | Emailing a sole trader, which PECR forbids | Count a legal form only next to the company's own name ("Acme Energy Ltd"), or a company number in a "registered" phrase. A bare marker elsewhere is ignored. Companies House stays the strong proof | P0 | S |
| A3 | **The country can be inferred from weak signals**: a phone prefix or a UK postcode anywhere on the page. A German company with a London office number would be treated as GB | `facts.py::infer_country` | The wrong country rule (for example GB instead of a blocked DE) | Accept automatically only an operator-given country, a stated registration, or the domain's country code. Weak signals become a suggestion stored in research; the lead is held as `country_unknown` with "probably GB, because ..." shown on screen for one-click confirmation (needs C1) | P0 | S |
| A4 | **Erasure ("forget") is built but cannot be used**: no command, no API, no screen. The draft-deletion half (removing drafts from the mailbox) is not wired | `services/forget.py` returns draft ids; nothing calls it | An erasure request cannot be honoured. Emails are being sent by hand already, so requests can arrive now | `outbound forget EMAIL`, `POST /api/forget`, and a **Forget this person** action on the lead page (with a confirmation). After the commit, delete the returned drafts through `Mailbox.delete_draft` | P0 | M |
| A5 | **Opt-outs are promised but not processed.** Every footer says "reply unsubscribe and we will stop", and replies are not read until Phase 4 | Footers; no inbox reading | Ignoring an opt-out | **Suppress** button on the lead page (adds the address or domain, cancels unsent messages, deletes their drafts). The manual tells the operator to check replies by hand until Phase 4. The quality report counts suppressions | P0 | S |
| A6 | **Cached vendor answers that contain personal data are kept for ever** in `provider_calls.response` | `metered.py`; no purge | Storage-limitation principle (GDPR, DPDP) | `outbound purge` (and a tick step) blanks `response` older than the cache lifetime (90 days), keeping cost, outcome and timing. Setting `retention_days` | P1 | S |

### B. Correctness and robustness

| ID | Gap | Evidence | Risk | Fix | Pri | Effort |
|---|---|---|---|---|---|---|
| B1 | **Leads can loop for ever, invisibly.** When the guard says "hold" for a lead at `qualified`, `email_ready` or `approved`, or delivery finds the email no longer safe, the lifecycle has no way to hold it, so it is deferred every hour, writing an event each time | `state_machines.py` has no `held` exit from those statuses; `runner._defer`; `deliver.py` | Leads that never move, a growing event table, and the operator never told | Allow `qualified`, `email_ready` and `approved` to move to `held` (the hold reason fixes where it resumes, as today). Delivery that finds an unsafe email holds it with the reason. A deferral is logged once, not every hour. No migration: transitions live in code, not in a `CHECK` | P0 | S |
| B2 | **Two runs can work on the same leads at once** (the worker, a CLI `run`, a cron `tick`). Optimistic locking stops a double write, but both may pay for the same vendor call before either has cached it | No run lock in `runner.py` | Double spend; confusing reports | One pipeline run per workspace at a time: refuse to start (CLI) or keep queued (worker) while another run is `running` and was active recently | P1 | S |
| B3 | **A run whose worker died stays `running` for ever.** The UI shows it as running and the lock in B2 would block everything | No stale-run handling in `audit.py` / `worker.py` | A stuck queue | The worker marks `running` runs with no progress for 30 minutes as `failed` ("worker stopped") on start and on each poll. Runs record a heartbeat in `counts` | P1 | S |
| B4 | **Budget changes do not reach a running worker.** The per-prospect ceiling is read once, when the pipeline is assembled | `pipeline.py` passes a fixed `BudgetPolicy` | The operator lowers the budget and it is ignored until a restart | `BudgetPolicy` reads the workspace setting at check time (one small query per paid call) | P1 | S |
| B5 | **Model spend is invisible to the budget.** No model has a default price, so every model call costs $0 in the ledger and the per-prospect ceiling never counts it | `pricing.py::DEFAULT_LLM_PRICES` is empty | Overspend with a paid model; wrong cost reports | Ship prices for the common default models; record the provider's own reported cost when it sends one (OpenRouter does); warn at start-up and in the setup check when the configured model is unpriced | P1 | S |
| B6 | **Rejecting an email ends the company for good.** `rejected` is final, so the only way to get a better email is to edit it by hand | `state_machines.py`; Review screen | Good leads lost because one draft was weak | Split the action: **Rewrite** (cancel this message, send the lead back to `email_ready` with the operator's instruction stored as a note the writer reads) and **Reject lead** (today's behaviour). Needs `copy_ready` → `email_ready` in the lifecycle | P1 | M |
| B7 | **Scheduled work only happens if cron is set up.** Retries, catch-all answers and the Sent sync run only on `outbound tick`; a web-only operator never gets them. Approved emails are drafted only when someone starts another run | `worker.py` executes queued runs only | Catch-all leads stay held; sent emails never recorded; approvals sit waiting | The worker runs a tick every 15 minutes when idle (setting), and queues a deliver-only pass right after an approval | P1 | S |
| B8 | **The mailbox list is not used.** Drafting and the Sent sync use the login in `.env`; the Mailboxes screen only checks DNS, and `messages.mailbox_id` is never set | `pipeline.py`, `deliver.py` | Confusion; a later multi-mailbox phase starts from wrong data | Record the configured mailbox on start-up (create its row if missing), set `messages.mailbox_id` at delivery, and label the screen honestly ("the mailbox in `.env`") | P2 | S |
| B9 | **Two settings say which catch-all resolver to use**: `CATCH_ALL_RESOLVER` in `.env` and `catch_all_resolver` in the workspace settings. Only the first is used | `config.py`, `defaults.py` | Editing the wrong one | Drop the workspace copy; show the active resolver in the setup check | P2 | S |

### C. Operator workflow: dead ends in the app

| ID | Gap | Evidence | Fix | Pri | Effort |
|---|---|---|---|---|---|
| C1 | **A saved company cannot be edited** (country, name, priority, campaign), although the API supports it. A `country_unknown` hold cannot be fixed from the browser | Manual §13; no form on the lead page | Edit form on the lead page using `PATCH /api/companies/{id}` with `row_version`; "Confirm suggested country" button for A3 | P0 | S |
| C2 | **Consent cannot be recorded from the browser**, so `consent_required` holds and blocked countries cannot be resolved even when the operator has real consent | API exists; no screen | **Record consent** on each person (basis and evidence), then release the hold | P1 | S |
| C3 | **A `needs_operator` hold cannot be released from the browser**; the button always fails with "no default" | `LeadDetail.tsx` sends `{}` | Release offers the allowed resume points when there is no default | P1 | S |
| C4 | **A person or an email address cannot be added to an existing company.** Adding the same website again only adds notes | `intake.py::_merge` | **Add person** on the lead page (name, title, optional email; the email is verified like any operator address). Intake merges a new person or email into an existing company too, if they are new | P1 | M |
| C5 | **Override on a blocked country is useless**: *Override and qualify* moves the lead on, and the next guard stops it again | `runner/guards.py` | Hide the override for country blocks and point to C2 (consent). Keep it for a low fit score | P1 | S |
| C6 | **No setup check.** The app does not say what is missing: mailbox login, model key, an unpriced model, an unreviewed sender profile, no Companies House key, DNS not set | Found by the first live run and the `serve` error | `outbound doctor` and a **Setup** card at the top of Settings, from one `GET /api/setup` that lists each item as ok, warning or missing, with the fix | P1 | S |
| C7 | **No reports screen.** Quality and cost exist in the API and CLI only | `routers/runs.py` | A small Reports page: unedited share against the 80% target, flag rate, holds by reason, spend by vendor and per prospect | P2 | S |
| C8 | **An ambiguous Sent match is only visible in the timeline** | `stages/sync.py` writes an event | Show it on the Review and Leads screens, with "this is the one" to settle it by hand | P2 | S |
| C9 | **Small missing controls:** choosing a campaign when starting a discovery run; allowing personal email domains when adding a target | `Runs.tsx`, `Targets.tsx` | Add both controls | P2 | S |

### D. Research and copy quality

| ID | Gap | Evidence | Fix | Pri | Effort |
|---|---|---|---|---|---|
| D1 | **People often have no job title.** Many team pages show names and photos only (Open Climate Fix: "Photo of Dan Travers"), so ranking by wanted titles has nothing to compare | Cached Tavily page; live run | Take the title from the finder when it returns one (Hunter returns a position), and run one public title search for the top names when the page has none. Rank untitled people last | P1 | M |
| D2 | **Pages are guessed by path** (`/about`, `/team`, `/news`, `/contact`). Many sites use other paths (`/about-us`, `/company`, `/people`), so whole pages are missed | Live run read 2–3 of 5 pages | Read the home page's links and choose the about, team, news and contact pages from them; fall back to the guessed paths | P1 | M |
| D3 | **Discovery adds any website a search result points to**, including news and directory sites, and research spends money on each before the fit check | `services/intake.py::discover_rows` | Skip known news and directory domains; check the search result's title and snippet against the ideal customer before adding; mark discovered rows for a quick confirm in Targets | P2 | M |
| D4 | **One model for every task.** Research summaries, fit scoring, copy and the critic all use the same model, so quality and cost cannot be balanced | `config.py` | Optional `LLM_MODEL_COPY` (the writer and critic) beside the default model | P2 | S |
| D5 | **Unverified live:** ZeroBounce, OrbiSearch, Scrubby, Companies House, the IMAP mailbox, and whether Tavily honours `site:` in a query | Phase 2 live-run notes | A scripted live check per vendor, on the operator's own addresses (`scripts/live_check.py`), recorded in the phase documents | P0 | S |

### E. Engineering and operations

| ID | Gap | Evidence | Fix | Pri | Effort |
|---|---|---|---|---|---|
| E1 | **None of Phases 0–3 is committed.** Everything since the first commit is uncommitted work on `phase-0/fix-and-bakeoff`, so one mistake could lose it all. The GitHub remote exists, but CI has never run | `git log` shows one commit | Commit in reviewable pieces (one per phase), push the branch, open PRs, and let CI run on SQLite, Postgres and the web job. **Needs the operator's go-ahead** | P0 | S |
| E2 | **The pre-commit hooks are not installed** | No `.git/hooks/pre-commit` | `uv run pre-commit install` | P1 | S |
| E3 | **No backup.** All leads, history and costs live in one SQLite file | No command | `outbound backup` (the SQLite online-backup API, to `data/backups/` with a date) and a line in the manual on scheduling it | P1 | S |
| E4 | **The legacy package is still there** and its dependency group is installed | Phase 2 retirement step | Delete `agent/` and the `legacy` group after the live run in this phase | P1 | S |
| E5 | **Phase 0's bake-off has not run**, so the finder chain is still a guess | Phase 0 gate | Needs the 30 known contacts from the operator | P1 | S |
| E6 | **A LangGraph deprecation warning prints on every command** | `outbound/__init__.py` filter does not catch it | Filter by category at import time, before LangGraph loads | P2 | S |
| E7 | **The API documentation page is open without a login** | `/api/docs` | Put it behind the login | P2 | S |
| E8 | **The production tables are probably readable and writable through Supabase's Data API.** They are in the `public` schema with row-level security off. Supabase serves `public` through PostgREST and, by its default privileges, grants those tables to `anon` and `authenticated`, so anyone holding the project's anon/publishable key (public by design) can reach every lead, contact and email. The app never uses the Data API | Found by the SaaS planning review (2026-10-23); DEPLOY.md §1.2 | Data exposure | In the Supabase dashboard: check the Security Advisor ("RLS disabled in public"), turn the Data API off, and run `REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;` (also sequences, functions and default privileges). Phase 6a adds a catalog test that fails if those roles hold any grant | **P0** | S |

---

## 4. Work packages, in order

Each package is one PR. Each lists its gaps; the tests must exist before the package is done.

### 3b.1 Save the work (E1, E2) — first, with your go-ahead

- Commit Phases 0–3 as separate commits, push, open the PRs, and fix whatever CI finds.
- Install the pre-commit hooks.

**Done when:** CI is green on GitHub for all three jobs.

### 3b.2 Compliance fixes (A1, A2, A3, A5, C1)

- Empty seeded claims; sender profile must be reviewed once before copy runs.
- Incorporation markers must belong to the company's own name; weak country signals become a suggestion and a hold.
- **Edit** form on the lead page, and **Confirm suggested country**.
- **Suppress** action on the lead page, cancelling unsent messages and deleting their drafts.

**Tests:** facts rules with partner names and foreign phone numbers; the copy stage refusing an unreviewed profile; suppression cancelling a drafted message and deleting the draft; the edit form's 409.

### 3b.3 Forget (A4)

- `outbound forget`, `POST /api/forget`, and the lead-page action, with mailbox draft deletion after the commit.

**Tests:** the existing forget scan, plus draft deletion and a forget for an address that is not held.

### 3b.4 No dead ends (B1, C2, C3, C5, B6)

- Hold from `qualified`, `email_ready` and `approved`; delivery holds an unsafe email; one deferral event, not one per hour.
- **Record consent** on a person; release offers resume points; no override for country blocks.
- **Rewrite** versus **Reject lead** in Review.

**Tests:** a transition test per new edge (domain); every hold reason resolvable through the API; the rewrite path producing a second message with the operator's instruction in the prompt.

### 3b.5 Runs you can trust (B2, B3, B4, B5, B7)

- One run at a time; stale runs failed with a reason; budget read live; model prices and provider-reported cost; the worker ticks when idle and delivers right after approval.

**Tests:** two runners started together make one set of paid calls; a stale run is failed; lowering the budget stops the next paid call without a restart; an unpriced model warns.

### 3b.6 The operator can see what is wrong (C6, C7, C8, C9, B8, B9)

- `outbound doctor` and the Setup card; the Reports page; ambiguous Sent matches on screen; the two missing controls; the mailbox row recorded and used; one resolver setting.

**Tests:** each setup item reported as ok, warning or missing; a Playwright step that opens Reports.

### 3b.7 Better research (D1, D2, D3, D4)

- Titles from the finder and one title search; pages chosen from the home page's links; discovery filtering; an optional copy model.

**Tests:** ranking with and without titles; page selection from a fixture home page; discovery skipping news sites.

### 3b.8 Operations (A6, E3, E6, E7)

- Purge of old cached personal data; `outbound backup`; the warning silenced; the API docs behind the login.

### 3b.9 Live check and retirement (D5, E4, E5)

- `scripts/live_check.py` against each vendor and the mailbox, on the operator's own addresses.
- The 5-target live run of the gate.
- The bake-off, if the 30 contacts are ready.
- Delete `agent/`.

**Done when:** the gate at the top of this document is met.

---

### 3b.10 Lead journey page (added during the work)

A read-only dashboard for one lead: how it arrived (import row, batch, who, when), the eight pipeline stages with their state, per-stage details and incidents, and the vendor calls and cost of each stage. `GET /api/companies/{id}/journey`, built by `services/journey.py` from rows that already exist, so there is no schema change. The page is `web/src/pages/LeadJourney.tsx`, linked from the leads table and the lead page.

**Tests:** API tests for a new, held, failed, disqualified and waiting-for-review lead, the origin of an imported lead, per-stage cost adding up, and an unknown id; a Playwright step that opens a lead's journey and uses the stage tabs.

### 3b.11 Guided tour (added during the work)

A first-visit tour of every screen with **Next**, **Skip section** (jumps to the next screen) and **End tour**, restartable from the **Tour** button. The text and targets are data in `web/src/tour/steps.ts`; the player is `web/src/tour/Tour.tsx`. Anchors are `data-tour` attributes (`Card tour="..."`). Updating it is a standing rule for UI changes (CLAUDE.md, working conventions).

**Tests:** `web/e2e/tour.spec.ts`: opens on a first visit and End tour closes it for good; Skip section opens the next screen at its first step; a walk of every step against a real lead that fails when a target is missing (checked by renaming one).

### 3b.12 The right person gets the email (added during the work)

Found by the operator in use (2026-10-19): on rebase.energy the operator gave the CEO's address and recorded his consent, but the campaign's titles prefer a CTO, so the CTO (found by Hunter) was ranked first and the draft was written to him; the country check passed on the CEO's consent because consent was counted for anyone at the company. Also: the same consent recorded twice, a second card for a person first added by first name only, and no way to change an address, remove a wrong match or move a waiting email to someone else.

- `rank_contacts` puts operator-chosen people first: added by the operator, given an address by the operator, or with a recorded consent. `contacts.make_first` after add, edit-address and consent fixes the tie at rank 1 for people added after ranking.
- `policy_decision_for(..., recipient_id=...)`: the email, copy and deliver steps count only the recipient's consent; the gate and guard still count anyone's (no recipient yet). Copy now holds instead of writing when the recipient is not allowed.
- `consents.add` keeps one active consent per basis; **Add a person** updates a person with the same name (case and accents ignored, a first name matching a full name); **Edit** gives a new address, the old one kept as history.
- New: **Write to this person instead** (`POST /api/companies/{id}/change-recipient`; `email_ready`, `copy_ready` and `approved` may go back to `contacts_found`, the waiting email is cancelled) and **Remove** (`DELETE /api/contacts/{id}`, refused once written to; `ErasureRepository.delete_contact`).

**Tests:** ranking with a chosen CEO against a wanted CTO; recipient-only consent; idempotent consent; same-name dedupe; rank after a late add; remove and its refusal; change recipient with the email cancelled; the API for both; the state-machine table.

### 3b.13 Real company names and the right people (added during the work)

Found by the operator in use (2026-10-19): a discovery run named every company after the search hit's page title ("6 Grid Trends to Watch in 2026" for amperon.co, "AI Foresight Trends Report" for ltm.com), and the LinkedIn search then used that title and accepted anyone sharing one word with it ("foresight", "grid", even "the"). Six people at other companies were attached to three leads. "tata power" resolved to the group's tata.com without asking.

- Discovery stores the website and the page it was found on, never a name; it asks for companies, takes twice the hits and skips articles and documents.
- Research runs the site worker first; it returns the company's own name, which is saved (operator names are kept) and used by the legal, signals, persona and fit workers.
- `search_people` confirms a person only when the profile's employer is the company (whole name or website name); a mention only gives `unconfirmed` (new contact status, migration 0003), anyone else is dropped. `read_profile_title` reads "Title at Company", keeps the title, and strips emoji. No people are taken from other sites' pages when the site could not be read. Research dedupes people by name too.
- `match_confidence` needs the whole name in the website's name; a partial one ("tata" for "tata power") asks the operator.
- **Confirm they work here** on the lead page (`POST /api/contacts/{id}/confirm`); the contacts stage says so when only unconfirmed people were found.

**Tests:** the real LinkedIn results (Dan Roth, Jigar Shah, Adam Shaw, Damian Płaza, Isak Bergset); one shared word is not enough; name from the site, used by the search and fit; operator name kept; unconfirmed saved; no people from a thin site; profile-title parsing; website matching (tata); discovery without names and without documents; confirm; migration 0003 up and down on both databases.

### 3b.14 Country rules you can configure and skip (added during the work)

Asked for by the operator (2026-10-20): skip the country rule for one lead at chosen stages, from the lead or journey page, or switch it off for the workspace; and configure the rules fully.

- `companies.policy_skip_from` (migration 0004): the rule is skipped from that stage onward. `policy_decision_for(..., stage=...)` returns ALLOW with `skipped` when the workspace switch `country_policy_enabled` is off or the lead's skip covers the stage. Suppression is separate and always applies.
- A guard that finds a block now **holds** the lead (`needs_operator`) instead of suppressing it, so revoking a skip or switching the rules back on never ends a lead.
- `LeadService.skip_policy` (reason required, `policy_skip_granted` event) moves a lead the rule stopped back to where it stopped; a later start is refused. `revoke_policy_skip` until approval; `release_policy_holds` after switching the rules off.
- The footer is its own setting, `footer_enabled` (default on): the country's footer, or a default one, also when the rule is skipped.
- Country rules: add any country with any rule, edit *Only addresses from*, remove a rule; `policy_changed` and `policy_deleted` events.
- Screens: *Country rule* card on the lead page, the same control in the journey's stage panel, the switch and bulk release on Policies and privacy, a red banner while the rules are off, the footer switch under Limits.

**Tests:** the skip rule per stage; rules off qualifies a blocked country; suppression still wins; a block at the gate and a hold at contacts each resume where they stopped; a later start refused; revoke until approval; release after switching off and holding again after switching on; the country's footer kept; the default footer and no footer; policy change and removal events; the API.

### 3b.15 Skip the email and person checks, confirmed at approval (added during the work)

Asked for by the operator (2026-10-20): the email check and the person check should be skippable for a lead, provided the operator confirms it when approving. On tilt-energy.com the operator's address for the CEO came back *unknown*, and the lead could only move on by adding a second card for the same person.

- `contact_emails.verification_skipped` (migration 0005), set by **Skip the check** with a reason (`email_verification_skipped` event), for any status including *invalid*. `is_sendable` treats such an address as sendable in the waterfall (no verifier or finder call), the copy step and deliver; suppression still wins. A lead failed at the email step or held on a catch-all goes back to the email step and on.
- The person check is the *unconfirmed* status from 3b.13; **Confirm they work here** is the skip. The first-and-last-name rule only stops the paid finders, never an address the operator gives, so it needs no skip; the screens say so.
- `ReviewService.approve(acknowledge_skips=...)` refuses an email that relies on a skipped check (country rule skipped or off, address without proof, confirmed person) unless acknowledged, records `approved_with_skips`, and refuses a suppressed address. Review shows the list and a required tick box; the CLI takes `--acknowledge-skips`.

**Tests:** the waterfall uses a skipped address of every status without paying; suppression still wins; the Tilt case through the email step; reason required; refused for a suppressed address; approval refused without, recorded with; every kind of skip listed; restore until approval; a browser test from a held lead to an acknowledged approval.

### 3b.16 Clean up the first discovery run's data (added during the work)

`scripts/fix_discovery_data.py`, run once after 3b.12 to 3b.15 are deployed. It goes through the services, so every change writes its event, and it prints its plan without changing anything unless given `--apply`. It renames the discovered leads after their own sites (as the engine, not as an operator edit), removes the six people a search attached to the wrong companies, replaces the tata.com lead with tatapower.com, and moves the rebase.energy draft from the CTO to the CEO who gave consent; `--rerun-research` also sends amperon.co back to research. Each step finds its lead by domain and person by name and skips itself once done.

**Tests:** a seeded copy of the live data: the plan, the result of applying it, and an empty plan on a second run.

### 3b.17 Model calls that do not break the run (added during the work)

Found by the operator (2026-10-21): research failed on a free reasoning model with *not valid JSON* (a reply of `{"people":{ "people": []}`), *cut off at the token limit* after about two minutes of thinking, and 429s.

- `ask_json` asks once more, with a reminder, after a broken, mis-shaped, empty or cut-off reply; a rate limit is left to the HTTP client. Extraction calls (site, signals, persona, fit) run at temperature 0.2 instead of 0.7.
- `LLM_REASONING_EFFORT` sends OpenRouter's `reasoning.effort` when set. Reasoning tokens count against `LLM_MAX_TOKENS` (OpenRouter's docs), which is why a high limit alone only made the model think longer.
- `LLM_COPY_MODEL` runs the email on its own model (same provider, key and address) while research stays on `LLM_MODEL`; the ledger records the model per call.

**Tests:** a broken then good reply, two broken replies, a cut-off reply and a rate limit; the temperature on both tries; the effort sent only when set; settings give a separate writer model; the pipeline writes with it.

### 3b.18 Recent news in research (added during the work)

Asked for by the operator (2026-10-22): the emails should open with something recent from the news, not the company's own website. Nothing searched for news; `research.news` was only what the site's `/news` page said.

- `SearchProvider.search(topic, days)` and `SearchHit.published_date`; Tavily sends `topic`, `start_date` and `filter_by_published_date` (it has no `days`), and news is cached for 7 days.
- A news worker after the site worker: the site names its `sector`; two news searches (company by name, 180 days; market terms by sector, 90 days). Undated, old or other-company hits never reach the model; the model picks hits by number, so dates, headlines and links are always the search result's. A failed search never fails the lead; a budget error does.
- `research.news_items` and `research.triggers` (and `sector`) are saved in the existing JSON column. The lead page lists them as links, the journey as facts. No migration.
- About $0.016 more per lead (two basic searches) plus one model call.

**Tests:** the adapter request and mapping (new fixture); the metered cache key and 7-day TTL; real-shaped hits kept, old, undated and other-company hits dropped; invented numbers ignored; no dated news means no model call; search failure versus budget error; the stage saves the items; API shows them on the lead and the journey.

### 3b.19 Emails that read like a person wrote them (added during the work)

Found by the operator (2026-10-22): every email was the same 3-liner (what they do, what we do, short call?), about 50 words, opening with the company's own website. Code joined five one-sentence parts; the prompt asked for 48 to 72 words; the checker wanted 50 to 85 words and reading grade 6.5.

- The writer returns `{subject, body, based_on}`; code adds the greeting (`sender_profile.greeting`), signature and footer. A new brief: open with the most recent dated news (company, then market, then a site fact), give a view, one relevant thing the sender has done, one clear ask fitting `sender_profile.outreach_goal`; 2 to 4 paragraphs in a person's voice; no lists, flattery or hype; nothing invented.
- The operator's past emails (`sender_profile.style_examples`, up to four) are given as voice reference, labelled not to be copied; corrections on Review still teach most.
- The checker: length from `settings.email_min_words`/`email_max_words` (120–200 by default) on the body alone; grade 10; one or two questions; new rules for bullet lists and em dashes; a much longer list of stock and machine-sounding phrases (every tell in the operator's past emails). Code also checks `based_on` is a url research found, and that recent news is used when there is some. Then one model check: grounded and human. A rewrite sees its last draft.
- Review shows **Opens with:** (the news item, linked) and **Write it again** (`POST /api/review/{id}/rewrite`: cancel and write afresh to the same person). Settings gain the email length and the *How you write* card.

**Tests:** assembly and greeting choice; the length from settings reaches the writer and the checker; the old 3-liner now fails on length; bullets, dashes and stock phrases caught without a model; a made-up source rejected; recent news must be the opening; the operator's past emails and goal reach the prompt; the opening item is saved; the settings and their limits; rewrite through the API and the browser.

### 3b.20 Run pages, Research again, and Review from the journey (added during the work)

Asked for by the operator (2026-10-22).

- **A page per run** (`/runs/{id}`, `GET /api/runs/{id}/leads`): every lead the run moved, held, failed or deferred, with each step and its reason or error, each linking to the lead and its journey; it refreshes while the run is going. No new table: the runner now writes `run_id` into the `status_changed` (and `deferred`) events it records, and `EventRepository.for_run` reads them back (a JSON field query that works on SQLite and Postgres).
- **Research again** on the lead page (`POST /api/companies/{id}/research-again`): any status before the mailbox may go back to `new`; a waiting or approved email is cancelled; operator values, people and addresses are kept. Refused for a lead not yet researched or whose email has left.
- **Open in Review** next to an email waiting for review in the lead page's Emails section (moved there from the journey at the operator's request): `/review?message=<id>` opens that email.

**Tests:** a pipeline run lists both leads with each step and a quiet second run lists none; a failed lead carries its error; research again cancels the email and keeps the people, and is refused before research and after the email left; the API for both; browser tests for the run page and its links, Open in Review, and Research again.

### 3b.21 Ask for changes on Review (added during the work)

Asked for by the operator (2026-10-22): change the final copy in any way (tone, more information, a full rewrite) without editing by hand.

- **Ask for changes** under the email on Review: free-text instructions (with one-click starters), **Rewrite with these changes** rewrites the text as it is in the editor. `ReviewService.revise` / `POST /api/review/{id}/revise` call the writer model (`metered_writer_or_none`, through the meter, attributed to the lead) with `REVISE_SYSTEM_PROMPT`: the operator's instructions come first and their facts count as true; the footer is cut off before the model and put back by code. The result and its lint report go back to the editor, unsaved; approving stores it as the operator's version. Each request is a `revision_asked` event.

**Tests:** revised as asked with the operator's edits and without the footer reaching the model; nothing saved until approval, which records it as an edit; refused without instructions, without a writer, or once approved; the API; a browser test from a one-click starter to approval.

## 5. Effect on the schema and the documents

- **No new tables or columns.** `sender_profile.reviewed_at`, `retention_days`, and the run heartbeat live in existing JSON columns. The new lifecycle edges are code, not database constraints. Update the value conventions in [SCHEMA.md](../SCHEMA.md) §7.
- **[PLAN.md](../PLAN.md):** the lifecycle table (new `held` exits, `copy_ready` → `email_ready` for a rewrite), the deliver row, and the worker's tick.
- **[USER_MANUAL.md](../USER_MANUAL.md):** remove each "Known limits" row as it is fixed; add Forget, Suppress, Rewrite, Record consent, Edit, the Setup card, Reports, backups.

## 5b. Outcome (the Phase 3b pull request)

**Fixed, each with a regression test:** the file-disclosure bug in the web route (`GET /..%2f..%2f.env` returned the `.env`), security headers and limits, typed errors with no detail in a 500, a login-protected API document; compliance (no seeded claims, sender-profile confirmation gate, stricter UK and country evidence, fenced web text in prompts); forget and suppress from the CLI, API and screens, with erasure checked by scanning every text column; no silent loops (held leads hold, over-budget leads can still be drafted, unsafe deliveries hold), migration 0002; one metered path, timeouts, typed settings, a worker that survives errors; layer rules enforced by import-linter and ruff; tests blocked from the network; web: edit, consent, release choice, suppress, forget, accessible tabs, shared loading and error states, sign-out on 401, typed upload; the lead journey page; the guided tour; secret scanning, dependency audit, Dependabot; langgraph 0.3 to 1.x to clear advisories.

**Found by the operator in use (2026-10-19):** a lead in India (default rule: consent required) was held at the gate, before any person was known. Consent is recorded per person, so there was nobody to record it for; releasing sent the lead back to the same check and it was held again, four times. Fixed: **Add a person** on the lead page (C4 for new people), with consent recorded in the same step and the hold released; a release of a country-rule hold is refused, with the reason and the remedy, while nothing has changed. Tests: service, API and a browser test of the whole case. A follow-up: a one-word name left the lead failed at the email step ("has no first and last name") because the finders need both; Add a person now refuses it unless a work email is given, and **Edit** on a person (`PATCH /api/contacts/{id}`) corrects a name, title, or adds an address, retrying the failed step.

**Delete a lead (2026-10-19):** there was no way to remove a lead. `POST /api/companies/{id}/delete`, `outbound delete-lead` and a red card on the lead page remove the lead and everything under it in dependency order. Safeguards: the domain must be typed (checked again on the server); a lead that has been emailed is refused (suppress instead); drafts in the mailbox are deleted, and any that cannot be are listed; optionally the domain is blocked. The cost ledger keeps its rows (spend is real) but loses the link to the lead and the stored vendor answers; the import row loses its text; all events for the lead are deleted except one `lead_deleted` record with counts and no personal detail. The runner now skips a lead deleted mid-run instead of failing the run. Tests: service (a scan of every column for the person's data, the ledger, another lead untouched, drafts, wrong confirmation, sent mail, workspace isolation, a run deleting the lead it is working on), API, CLI and a browser test.

**Live check (2026-10-19, `scripts/live_check.py`, a few cents):**

| Vendor | Result |
|---|---|
| LLM | answers |
| Tavily | search, `site:` search and page extract work |
| Mailbox (IMAP) | login, save a draft, find it, delete it: all work |
| Hunter, ZeroBounce, OrbiSearch, MyEmailVerifier verifiers | each returned *valid* for the operator's own address |
| Companies House | works (name search returns matches). The key was in `.env` under the wrong name, `COMPANIES_HOUSE`; the variable the app reads is `COMPANIES_HOUSE_API_KEY` |
| Scrubby | **fails**: `api.scrubby.io` accepts the connection but never answers (read timeout). The base URL is a guess from partial docs; confirm it in the Scrubby account |

**Still open or deferred** (not in this PR): one run at a time and stale-run recovery (B2, B3), live budget read (B4), model pricing and the cost of failed replies (B5), worker auto-tick (B7), adding a person to an existing company (C4), setup check and Reports pages (C6, C7), research quality (D1 to D4), retention purge (A6), backups (E3), the bake-off with 30 contacts (E5), deleting `agent/` (E4), long functions, magic numbers into settings, a salted suppression hash, composite foreign keys before Phase 6, typed models for the JSON columns. textstat (and with it the unfixed nltk advisory) was dropped: it downloaded a word list from the internet on first use, which broke clean CI runners; the reading grade is now computed in `copy_lint.py`.

## 6. Decisions needed from you

1. **May I commit and push Phases 0–3 now** (3b.1)? Everything else is safer after that.
2. **Site-only incorporation markers (A2):** with no Companies House match, should a "Acme Energy Ltd" footer be enough, or should UK leads always need Companies House? The plan assumes the footer is enough, but only when the legal form follows the company's own name.
3. **Retention (A6):** is 90 days right for keeping vendor answers that contain personal data?
4. **Worker ticking (B7):** every 15 minutes, or should drafting and the Sent sync stay manual?

## 7. Deliberately left for Phase 4 or later

Reading replies and stopping a sequence, follow-up emails, bounce handling, automatic sending, more than one mailbox, more than one user. The manual already says so.

## 8. Before Phase 6a (the SaaS track)

The SaaS track ([phase-6-saas-ready.md](phase-6-saas-ready.md)) builds on these. Finish them here so 6a can stay about tenancy.

| Item | What 6a needs from it |
|---|---|
| **E8** Data API closed | No exposure while the tenancy work goes on. Do it first |
| **B2** One run per workspace (**done in 6a**) | A partial unique index, one `running` run per workspace (migration 0006). It also blocks a second CLI run. The multi-tenant scheduler relies on it |
| **B3** Stale runs (**done in 6a**) | `runs.heartbeat_at` (migration 0006) and recovery after 30 minutes without one |
| **B4** Budget read live (**done in 6a**) | The pipeline is assembled per run in 6a, and limits change at runtime in 6d |
| **B5** Model prices | The LLM is now DeepSeek served by DeepInfra (OpenAI-compatible). Set its prices in `LLM_PRICES`: credits and margins (6d) are wrong while model calls cost $0 in the ledger |
| **B7** Worker tick (**done in 6a**, as a timer in the worker rather than queued runs) | A tick run queued per workspace every 15 minutes. 6a's scheduler claims it like any run, and 6d's automatic resume runs in it |
| **E4** Delete `agent/` | Less to carry through the tenancy refactor |
| `web/` deleted | Its CI job signs in with the old password form; 6b replaces sign-in |

## Gate record

- Date:
- P0 gaps closed (IDs):
- Live run (5 targets, drafts in mailbox):
- Checked by:
