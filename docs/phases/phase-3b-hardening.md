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

## 5. Effect on the schema and the documents

- **No new tables or columns.** `sender_profile.reviewed_at`, `retention_days`, and the run heartbeat live in existing JSON columns. The new lifecycle edges are code, not database constraints. Update the value conventions in [SCHEMA.md](../SCHEMA.md) §7.
- **[PLAN.md](../PLAN.md):** the lifecycle table (new `held` exits, `copy_ready` → `email_ready` for a rewrite), the deliver row, and the worker's tick.
- **[USER_MANUAL.md](../USER_MANUAL.md):** remove each "Known limits" row as it is fixed; add Forget, Suppress, Rewrite, Record consent, Edit, the Setup card, Reports, backups.

## 6. Decisions needed from you

1. **May I commit and push Phases 0–3 now** (3b.1)? Everything else is safer after that.
2. **Site-only incorporation markers (A2):** with no Companies House match, should a "Acme Energy Ltd" footer be enough, or should UK leads always need Companies House? The plan assumes the footer is enough, but only when the legal form follows the company's own name.
3. **Retention (A6):** is 90 days right for keeping vendor answers that contain personal data?
4. **Worker ticking (B7):** every 15 minutes, or should drafting and the Sent sync stay manual?

## 7. Deliberately left for Phase 4 or later

Reading replies and stopping a sequence, follow-up emails, bounce handling, automatic sending, more than one mailbox, more than one user. The manual already says so.

## Gate record

- Date:
- P0 gaps closed (IDs):
- Live run (5 targets, drafts in mailbox):
- Checked by:
