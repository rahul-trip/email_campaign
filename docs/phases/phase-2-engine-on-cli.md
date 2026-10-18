# Phase 2 — Engine on the CLI

**Goal:** run the whole pipeline from intake to a mailbox draft from the command line, and prove the emails are good enough to send unedited.
**Depends on:** Phase 0 (ports, adapters, the chosen chain) and Phase 1 (schema, repositories).

**Status (2026-10-17): code complete and verified with fake vendors on SQLite and PostgreSQL 16.2 (1,163 tests at the time). The gate itself is waiting on live keys and a real run.** What is left to close the phase is the live work only: run the pipeline on real targets with the keys in `.env`, send 10 first emails, read the quality report, and then delete `agent/`. See the [gate record](#gate-record).
**Gate:**
- **Quality:** of the first 10 touch-1 emails sent, 8 go out without edits. This is measured automatically by comparing `generated_body` with the body the Sent sync finds.
- **Cost on rerun:** running the same targets file again makes zero paid calls and creates zero new drafts. Check with `provider_calls` grouped by outcome: no `hit` or `miss` rows, only `cache_hit`.
- **Retirement:** `agent/` is deleted.

## Scope

**In:**
- The `Metered` decorator and the budget guard.
- Tavily, LLM, Companies House and IMAP adapters.
- The runner and the scheduler tick.
- All nine stages up to drafting touch 1, plus the Sent-folder sync.
- CLI review.
- Moving reusable legacy code across, then deleting `agent/`.

**Out:**
- Automatic follow-ups and reply triage (Phase 4).
- Sending (Phase 5).
- The web UI (Phase 3).

## Tasks

### 2.1 Metered calls and the budget — done

As built: `providers/metered.py` holds a `Meter` plus one wrapper per port (`MeteredFinder`, `MeteredVerifier`, `MeteredResolver`, `MeteredSearch`, `MeteredRegistry`, `MeteredLlm`). Prices are in `providers/pricing.py` (the bake-off script now imports them). Tests: `tests/db/test_metered.py` (24, SQLite and Postgres).

Differences from the text below:
- The wrappers implement the same port as the thing they wrap, so a stage never sees the ledger. There is no generic `Metered(...)` call site.
- The calling run, company and contact come from a `call_scope(...)` context manager rather than being passed to every call.
- The resolver wrapper never caches a ticket, because a ticket depends on the vendor's own state. The finished answer is cached under its own operation (`resolve`), so a repeated address costs nothing.
- The LLM is not cached unless a task opts in with `ttl` (identical prompts normally want different drafts).
- Monthly caps and TTLs are constructor arguments; wiring them from settings happens with the runner in 2.3.

- [x] `providers/metered.py` — a `Metered` wrapper around any port method. For each call it:
  1. Computes `request_hash`.
  2. Looks up a successful `provider_calls` row within the TTL. If found, records a `cache_hit` and returns that response.
  3. Calls the `BudgetGuard`.
  4. Makes the call.
  5. Commits a `provider_calls` row in its **own** short transaction, with outcome, cost and latency.
- [x] `providers/budget.py` — `BudgetGuard` checks:
  - each provider's monthly cap, by summing `cost_micro_usd` since the start of the month;
  - the per-prospect ceiling, by summing the company's calls.

  It raises `BudgetExceeded` and records a `blocked_by_cap` row.
- [x] TTLs live in config. Defaults: search and extract 30 days, finder and verifier 90 days, LLM never (cached by prompt hash).

**Done when:**
- A cache hit makes no adapter call.
- A cap blocks the call and records it.
- Cost is recorded even when the stage raises afterwards.

### 2.2 Remaining adapters — adapters done, prompts move with their stages

- [x] `adapters/tavily.py` (`search` and `extract`) was built in Phase 0. Still to do here: carry over the domain blocklist from `agent/providers/discovery/_common.py` into intake.
- [x] `adapters/llm.py`: an OpenAI-compatible chat client, with `llm_json.parse_json_object` for fenced or chatty replies. Ported from `agent/providers/copywriter/llm_copywriter.py` with the same presets; returns token counts. `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL` and one key variable per vendor select it.
- [x] `adapters/companies_house.py`: company search by name, returning company type and status (free API key, behind a `CompanyRegistry` port).
- [x] `adapters/imap_mailbox.py`, implementing a `Mailbox` port (named so it does not clash with the `MailboxGateway` enum). Each call opens its own short IMAP session. The draft id is the draft's `Message-ID`, and `delete_draft(id)` serves the forget service. Folder names and credentials use the legacy variable names (`IMAP_HOST`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `DRAFTS_FOLDER`, `SENT_FOLDER`), so `agent/.env` values keep working:
  - `append_draft(message) -> remote_draft_id`
  - `list_sent(since) -> list[SentMessage]` with `rfc_message_id`, `to`, `subject`, `date` and `body`
  - `list_inbox(since)` (used in Phase 4)

  Port the connection and message building from `agent/tools/mailer/drafts/imap_provider.py` and `agent/tools/mailer/core/message_builder.py`.
- [x] Move all prompts into `outbound/prompts/` (research and copy done; `classify` arrives with reply triage in Phase 4) as one module per role (research, copy, classify). Keep the existing `agent/prompts.py` convention: a `*_SYSTEM_PROMPT` constant plus a `build_*_user_prompt()` function. Written together with the stage that uses each (2.5 research, 2.8 copy); classify waits for Phase 4.

**Done when:** each adapter passes its port contract test against recorded responses. (Met against hand-built fixtures; the IMAP adapter is tested against an in-memory server. Real captures replace the fixtures at the Phase 0 gate; the IMAP and Companies House adapters need one live check each.)

### 2.3 Runner and scheduler — core done; CLI commands arrive with the stages

As built: `stages/base.py` (`Stage`, `StageContext`, `StageResult`, `Reader`), `stages/policy.py` (`policy_decision_for`, shared by the gate and the guard), `runner/guards.py`, `runner/runner.py`, `runner/tick.py`. Tests: `tests/db/test_runner.py` (27, SQLite and Postgres).

Differences from the text below:
- A stage returns what to write as data (`StageResult`: next status, engine-written company fields, an optional `write(uow)` for child rows) and the runner applies it in one transaction. This is how the "no transaction across a network call" contract is kept without every stage managing sessions.
- Failures back off: the wait before a retry is 15 minutes times the number of attempts so far. `retry_failed` restores the failed stage's input status while attempts remain (3 by default). Stages that cannot fail a lead (deliver, sync) are deferred for an hour instead.
- Guard outcomes: a suppressed domain or a blocking country moves the lead to `suppressed`; a policy that now needs a person holds the lead where the lifecycle allows it and otherwise defers it; a lead over its per-prospect budget is failed with the reason.
- Periodic work that is not a stage (catch-all poll, Sent sync) is a `Job` run by `Tick`.
- `outbound run`, `outbound tick` and `outbound retry` are wired in once the stages exist (2.5 onwards), so they do not ship doing nothing.

- [x] `stages/base.py`: the `Stage` protocol (`name`, `input_status`, `handle(snapshot) -> StageResult`), plus `StageResult`, which holds the next status, any child rows to write, and the events.
- [x] `runner/runner.py`: `run_stage` as in [PLAN §5](../PLAN.md#5-architecture), and `run_pipeline(workspace_id, limit)`, which runs the stages in order. For each lead it runs the guards, then calls `handle` with no open transaction, then makes one short write. A failure is recorded with `failed_stage` and the run continues.
- [x] `runner/guards.py`: checks suppression, country policy (from Stage 3 onwards) and budget.
- [x] `outbound tick`: one scheduler pass. It picks up due `next_action_at` work, polls the catch-all resolver, and runs the Sent sync. Run it from cron or a launchd timer; there is no daemon.
- [x] Every run is wrapped in a `runs` row with counts and cost.

**Done when:** in a kill-and-rerun test, the run is killed after lead 3 of 6 with fake providers, and the rerun reaches the same final state with zero repeated paid calls.

### 2.4 Stage 1 — Intake — done

As built: `services/intake.py` (`IntakeService`, header matching, anchor detection, `DomainResolver`, `discover_rows`), `domain/countries.py`, `outbound targets import | add | pending | confirm` (`cli/targets.py`). Tests: `tests/db/test_intake.py` (51) and 6 in `tests/test_cli.py`.

Differences from the text below:
- Intake is a service the CLI (and later the API) calls, not a runner stage, because it turns input into companies rather than moving a company. Rows that wait are settled with `targets confirm`.
- Searches run before the database transaction opens, and one transaction then writes the whole batch. `--validate-only` writes nothing and makes no search; rows that would need one show as `pending`.
- Name matching is deterministic: 0.9 when the domain contains the company name, 0.65 when only the page text does, 0.4 otherwise. Only 0.9 passes the 0.8 bar, so a lookalike domain always waits for the operator.
- Values the operator typed (name, country, priority) are recorded as theirs, so the engine cannot overwrite them. Discovered companies carry source `discovery`, so they still face the fit gate.
- Discovery mode itself (`discover_rows`) is in place; the `--mode` switch on `outbound run` arrives with the run command.

- [x] `services/intake.py` and `stages/intake.py`. Covers the CSV/XLSX loader with loose header matching, plus `--company` and `--validate-only`.
- [x] Anchor detection and resolution, per [PLAN §9](../PLAN.md#9-intake):
  - tldextract for registrable domains;
  - the free-mail and platform blocklist;
  - a company-name search through Tavily, with confidence and `needs_confirmation` when below 0.8;
  - LinkedIn `/in/` profile URLs via a public search on the slug.
- [x] Merging into an existing company: notes are appended and differing values become events. Suppression wins. Supports the modes `manual`, `discovery` and `mixed`.
- [x] The intake report: read, accepted, merged, needs confirmation, rejected (with reasons).
- [x] `outbound targets confirm ROW_ID DOMAIN` resolves `needs_confirmation` rows.

**Done when:** there is a test per anchor type and per intake rule, including free-mail handling, platform domains, duplicates within a file, and an already-contacted domain.

### 2.5 Stage 2 — Research (LangGraph supervisor and workers) — done

As built: `stages/research/{facts,graph,stage}.py`, `prompts/research.py`. Tests: `tests/stages/test_research_graph.py` (34), `tests/db/test_research_stage.py` (5). LangGraph and textstat are now runtime dependencies (the `legacy` group keeps its own copy until `agent/` is deleted).

Differences from the text below:
- The graph is `pages -> supervisor -> site | legal | signals | persona -> fit`. A `pages` node (one Tavily extract of five URLs) runs first so workers share one fetch; if the site cannot be read, a search stands in and the result is marked `thin`.
- The supervisor is `plan_workers()`, a pure function with a test per rule.
- The legal worker is plain code, no model: country from the operator, else a stated registration, the domain's country code, a phone prefix or a UK postcode (strongest first); for GB, incorporation markers in the text, then Companies House. Corporate status needs positive evidence, otherwise `unknown`, so the gate holds the lead.
- The persona worker does the one public LinkedIn-title search itself when there is no team page, so the contacts stage no longer repeats it.
- Findings stored on `companies.research` include `site_emails` (addresses published on the company's own domain), used later by the email stage as a free first candidate.

- [x] `stages/research/graph.py`: a LangGraph `StateGraph`, used as a stateless function. It takes the company snapshot and returns `ResearchOutput`, with no checkpointer.
  - **Supervisor node.** Reads what the lead already has and decides which workers to dispatch. These rules are deterministic, in plain code, and unit-tested:
    - the persona worker is skipped when an operator gave a contact;
    - the legal-entity check only runs when the country is GB or unknown;
    - the signals worker only runs when the campaign has research questions.
  - **Site and trigger worker:** Tavily extract of the home, about, team and news pages; returns a summary, products, news and hook candidates (1 LLM call).
  - **Compliance and legal entity worker:** the ISO country from site signals and the TLD. For GB, incorporation markers in the footer (Ltd, Limited, LLP, PLC, an 8-digit company number), then Companies House as confirmation. Sets `legal_entity_type`.
  - **Campaign signals worker:** answers the campaign's `research_questions`, plus hiring and tech-stack signals via Tavily (1 LLM call).
  - **Persona discovery worker:** people with titles and LinkedIn URLs, from the team page first, then a public search such as `site:linkedin.com/in "<Company>" ("CEO" OR …)`.
  - **Fit node:** a 0–100 score with a reason, measured against the campaign's ICP (1 LLM call, or combined with the signals call).
- [x] Workers run in parallel through LangGraph fan-out. Every Tavily and LLM call goes through `Metered`.
- [x] Saves `research`, `research_answers`, `country_code`, `legal_entity_type`, `fit_score` and `fit_reason`, plus candidate contacts.

**Done when:**
- Supervisor routing has a test per rule.
- The graph runs end to end with fake providers.
- A UK sole trader (no incorporation markers, nothing found at Companies House) ends up `held` with reason `entity_unknown` at the gate.

### 2.6 Stages 3 and 4 — Gate and Contacts — done

As built: `stages/gate.py`, `stages/contacts.py`, `domain/ranking.py`. Tests: `tests/domain/test_ranking.py` (25), `tests/db/test_gate_and_contacts.py` (17).

- A failed fit is reported before the country is examined; a blocked country disqualifies (an operator can override); a policy that needs a person holds with the policy's own reason. The decision and its policy version are stored on the company.
- Contacts are ranked by wanted-title match (abbreviations spelled out, filler words ignored), then seniority, then existing order. An operator-given person is always first. A company with no usable candidate fails with a readable reason.

- [x] **Gate:** applies `passes_fit_gate` (manual leads bypass it but keep their score) and `decide_country_policy`, then moves the lead to `qualified`, `disqualified` or `held` and records `policy_decision` with its version.
- [x] **Contacts:** ranks candidates against `campaign.target_titles` with simple title matching and a seniority order; an operator-given person is rank 1. If research found nobody, runs one public search and stops there.

**Done when:** there are tests for each hold reason and for the ranking order.

### 2.7 Stage 5 — Email (inline-validated waterfall and catch-all) — done

As built: `stages/email/{patterns,waterfall,stage,poller}.py`. Tests: `tests/stages/test_waterfall.py` (24), `tests/stages/test_email_patterns.py` (20), `tests/db/test_email_stage.py` (16).

- Order per person: held addresses, a published address that fits the person, the cached pattern (one address), then the finders in config order. Every address is verified when found. `catch_all` goes to the resolver and ends the search for that person. At most three contacts are tried.
- An asynchronous resolver holds the company (`catch_all_resolving`, wake-up in six hours). `CatchAllPoller` is a tick job: an answer settles the address and releases the company to `contacts_found`, where the stage runs again and uses the resolved address or moves on.
- The stage checks the country policy against the chosen address's provenance before finishing, so a guessed Canadian address holds the lead (`consent_required`). The same lookup is used by the runner's guard for later stages.
- Writes happen once, at the end of the stage: new addresses (including invalid ones, so they are never retried), status changes and the primary address.

- [x] `stages/email.py`. For each contact in rank order:
  1. If `companies.email_pattern` is cached, build that single address and verify it. Never generate several permutations.
  2. Otherwise go through the finder chain in config order. Verify each result immediately.
     - `valid`: stop, and cache the pattern on the company.
     - `invalid`: try the next finder.
     - `catch_all`: submit to the resolver.
  3. With a real-time resolver (Enrichley): `catch_all_resolved`, or `catch_all_unverified` if it fails.
  4. With an asynchronous resolver (Scrubby): the email becomes `catch_all_pending` with `resolution_ref`, the company is `held` with reason `catch_all_resolving`, and `next_action_at` is set to the poll time. `outbound tick` polls, then moves the company to `email_ready`, or to the next contact.
  5. When every finder misses, move to the next contact. When every contact misses, the lead is `failed` with "no valid email".
- [x] Operator-given emails skip the finders, but are still verified.
- [x] The email provenance is recorded: `api_database`, `pattern_inferred`, `publicly_published` (when the address appears on the company site) or `operator_given`.

**Done when:**
- The waterfall order is tested.
- Exactly one address is ever verified per pattern.
- The async resolver path is tested through tick.
- Canadian leads with `pattern_inferred` emails are held by policy.

### 2.8 Stage 6 — Copy (LangGraph actor-critic) — done

As built: `domain/copy_lint.py`, `domain/footer.py`, `domain/editing.py`, `prompts/copy.py`, `stages/copy/{graph,stage}.py`. Tests: `tests/domain/test_copy_lint.py` (28), `tests/stages/test_copy_graph.py` (13), `tests/db/test_copy_stage.py` (7).

- The writer returns five parts; **code** assembles greeting, paragraphs, sign-off and footer, so length, structure and legal text never depend on the model.
- The critic runs the linter first and only asks a model one question (is the hook specific to this company?) about a draft that already passes. Two rewrites at most; a draft still failing goes on flagged, with the reasons shown to the operator.
- The footer is rendered from the country policy template and the sender profile. A blank sender field the footer needs fails the lead with the field names, before any model call. A placeholder signature (`[Your Name]`) also fails it.
- Few-shot examples are the latest edited messages of the same campaign (`final_body` and `edit_distance > 0`), as before-and-after pairs; the count comes from the workspace setting `few_shot_examples`.
- Subject lint is 2–5 lower-case words; reading grade at most 6.5 (Flesch-Kincaid via textstat).

- [x] `domain/copy_lint.py`: deterministic rules from config. Word counts exclude the footer.
  - Touch-1 body 50–85 words; follow-ups 25–50.
  - Subject 2–5 lowercase words.
  - Flesch-Kincaid grade 6.5 or lower (textstat).
  - Exactly one question-style call to action.
  - No links in touch 1; no banned phrases; correct country footer.
  - Returns a `LintReport`.
- [x] `stages/copy/graph.py`:
  - **Actor:** produces snippet JSON (`hook`, `relevance`, `value`, `ask`, `subject`) from the sender profile, research, contact, notes and few-shot examples.
  - **Assemble:** builds the body in code and appends the country footer.
  - **Critic:** runs the linter first, then an LLM specificity check.
  - Up to 2 targeted rewrites. If the draft still fails, it goes on with `lint_report.flagged = true`.
- [x] **Few-shot examples:** the last N messages in the same campaign (N comes from settings, default 5), taken from those with `edit_distance > 0` and a `final_body`, given to the actor as before-and-after pairs.
- [x] Creates the step-0 `messages` row (state `generated`, `snippets`, `lint_report`) and moves the company to `copy_ready`.

**Done when:** each linter rule has a test, the rewrite loop stops at 2, and few-shot selection is tested.

### 2.9 Stages 7 and 8 — Review and Deliver — done

As built: `services/review.py`, `stages/deliver.py`, `outbound review list | show | approve | reject`. Tests: `tests/db/test_review_and_deliver.py` (21), plus idempotent-draft tests for the IMAP adapter.

- An edit is stored beside the original with its edit distance and an `edited` event. An edit that removes the required footer is refused.
- **Delivery is idempotent.** The draft gets a Message-ID derived from the message and the mailbox is asked whether it already has it, so a crash between "saved" and "recorded" cannot leave a duplicate (the bug the legacy tool had).
- Everything is re-checked at delivery with `check_send`: address status, suppressions, contact status and the country policy with the address's provenance. A blocked country or a suppressed domain ends the lead (`suppressed`); anything else leaves it `approved` and tries again in an hour.

- [x] Review commands:
  - `outbound review list` shows the copy-ready queue with lint flags.
  - `outbound review show ID` shows the email next to the research.
  - `outbound review approve ID [--edit FILE]` and `outbound review reject ID --reason`.
  - Edits set `final_body`, `edit_distance` and an `edited` event.
- [x] **Deliver:** re-run the guards and `is_safe_to_send`, then `append_draft` over IMAP. Set the message to `drafted` and the company to `in_sequence`.

**Done when:** an unsafe email can never be drafted. Test this by changing the policy between approval and delivery.

### 2.10 Stage 9 — Sent-folder sync — done

As built: `stages/sync.py` (`SentSync`, a tick job). Tests: `tests/db/test_sent_sync.py` (12): unedited, edited, reply prefix and case, nothing sent yet, wrong recipient or subject, sent before the draft, two candidates for one draft, one mail fitting two drafts, several drafts each finding their own, and a repeat run.

- An exact single match records the Message-ID, send time and the body that went out, and `edit_distance` against what the engine wrote. An ambiguous case is flagged once (`sync_ambiguous`) and left alone.

- [x] Part of `outbound tick`. Read the Sent folder since the last sync and match each message to a `drafted` message by recipient, normalised subject and a time window starting at draft creation.
  - If exactly one draft matches: set `rfc_message_id`, `sent_at` and `final_body`, compute `edit_distance`, and set the state to `sent`.
  - If several match: log it, leave the state alone, and flag the message for the operator.

**Done when:** the matching tests pass on fixture mailboxes, covering an unedited send, an edited send and an ambiguous case.

### 2.11 Quality gate report and retirement — report done; retirement waits for the live run

As built: `services/reports.py`, `db/repositories/reports.py`, `outbound report quality | cost`, and the everyday commands `outbound run | tick | retry | status` (`cli/ops.py`, `pipeline.py`). Tests: six in `tests/test_cli.py` and the end-to-end suite `tests/db/test_pipeline_e2e.py` (5), which runs a targets list through every stage to a mailbox draft and a Sent match, then reruns it at zero paid calls and zero new drafts.

- `agent/` is **not deleted yet** on purpose. The plan says delete it once the new pipeline drafts the same target list, which needs live keys. Deleting it also removes `agent/.env`, which holds the only copy of the working credentials: move them to the root `.env` first.

- [x] `outbound report quality`: share of sent touch-1 emails with `edit_distance == 0`, the lint-flag rate, and the held share by reason (catch-all held share included).
- [x] `outbound report cost`: spend per prospect and per provider over a date range.
- [ ] Delete `agent/` once the new pipeline drafts the same target list. Keep `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` read-only as history. Move any still-useful tests over.

## First live test run (2026-10-18)

Two targets from the legacy workbook (Open Climate Fix, UK; WattTime, US) on a throwaway database, with live Tavily, Hunter, MyEmailVerifier and an OpenRouter model; no mailbox, so nothing was drafted.

- **WattTime** went through every stage to the review queue: research, five people from the team page, Hunter found an address that MyEmailVerifier marked valid, and the copy stage wrote a 70-word email at reading grade 5.5. The critic flagged its hook as not supported by the research, so it reached review flagged, as designed.
- **Open Climate Fix** was held as `entity_unknown`: UK, no incorporation marker on the pages read, and no Companies House key. Correct under the policy; a Companies House key would settle it.
- **Cost:** $0.051 for both leads ($0.0255 a prospect) with a free model. Rerunning made **no new paid vendor call**; only the model was asked again.
- **Fixed after the run:** a reasoning model ran out of output tokens at the old 1,000 limit and the JSON was cut off. The default is now 4,000 (`LLM_MAX_TOKENS`), and a cut-off reply is reported as such. The tests also no longer read a developer's `.env`.
- **Seen, not yet acted on:** the model returned names without job titles from the team page, so title ranking had nothing to work with; the default proof points in the sender profile come from the legacy examples and must be checked before any real email.
- **Not yet exercised live:** ZeroBounce, OrbiSearch, Scrubby, Companies House and IMAP.

## Closing the phase (what only you can do)

1. Put the keys in the root `.env` (Tavily, the finder and verifier you picked after Phase 0, an LLM key, optionally Companies House and a catch-all resolver) and fill the sender profile (legal name, postal address, signature) in the `workspaces` row.
2. `uv run outbound db upgrade && uv run outbound seed`, then `uv run outbound targets import FILE`.
3. `uv run outbound run`, then `outbound review list`, `show`, `approve`; `outbound run` again to draft.
4. Send the first 10 from your mail client, then `outbound tick` and `outbound report quality`. The gate is 8 of 10 unedited.
5. Run `outbound run` on the same file again and check `outbound report cost`: no new paid calls.
6. Move `agent/.env` into `.env`, then delete `agent/` and the `legacy` dependency group.

## Gate record

- Date:
- Quality report (sent, unedited, share):
- Rerun check (paid calls, new drafts):
- Held share by reason:
- `agent/` deleted in commit:
- Checked by:
