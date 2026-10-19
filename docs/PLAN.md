# Outbound Engine — End-to-End Plan

**Status:** approved by the team on 2026-10-16. Every decision below is final.
**Build status (2026-10-18):** Phases 0–3 are code complete and tested with fake vendors; their gates wait on live runs with real keys. See [phases/README.md](phases/README.md). Where the build differs from the original wording, the text below has been updated and each phase document lists the differences.
**Where it lives:** this file is the source of truth for building the engine. The team reviewed the
[plan in Claude Docs](https://claude.ai/code/artifact/4cea76e3-1e09-442e-a719-22299ed78ece); any later change is made here, in the same PR as the code it affects.

Related documents:

- [SCHEMA.md](SCHEMA.md) is the column-level spec for schema v1.
- [phases/](phases/README.md) holds one document per delivery phase, with tasks, files and exit gates.
- [archive/](archive/README.md) keeps the superseded specs and notes, for history only.

---

## 1. Summary

The engine accepts or finds target companies, researches each one, finds and verifies a decision-maker's email, writes a short personalised email, and drafts it in the mailbox once a human approves it. Later phases add reply handling, follow-ups, automatic sending and multiple workspaces.

Development goes in this order: **schema, then relationships and integrity rules, then the backend engine, then the web app.**

Three research findings shaped the design:

- **Catch-all addresses would trip the bounce breaker.** Catch-all mail servers are 20–42% of B2B domains, and unverified catch-alls bounce at about 9%. Only safe-to-send addresses reach drafting; catch-alls go to a resolver first.
- **A fixed monthly data subscription breaks the $0.50-per-prospect budget at low volume.** A pay-as-you-go finder waterfall has no fixed cost.
- **A draft sent by hand gets a new Message-ID.** The engine has to read the Sent folder to time follow-ups correctly and thread them into the same conversation.

## 2. Scope

**Goals**

- Personalised, reviewed cold emails for 5–50 new prospects a week, at no more than $0.50 per prospect.
- Leads come from the operator (any partial detail), from search discovery, or both.
- Never contact a company twice, anyone suppressed, or anyone the country policy blocks.
- Resume after any failure without repeating a paid call.
- Later: follow-ups, reply handling, automatic sending, and several workspaces (SaaS).

**Non-goals**

- A CRM. Positive replies go out to one by webhook or export.
- Any channel other than email.
- LinkedIn scraping. Only public search results are read.
- Open or click tracking.

## 3. Decisions (all confirmed)

| # | Decision | Choice |
|---|---|---|
| 1 | Users | One operator now; SaaS later |
| 2 | Store | SQLite through SQLAlchemy 2 and Alembic; Supabase Postgres later; `workspace_id` on every table |
| 3 | Orchestration | A plain Python runner moves each company through its statuses. LangGraph subgraphs run only inside Research and Copy |
| 4 | Targets | A lead can start from one anchor: domain, website, company name, email, person and company, or LinkedIn profile URL |
| 5 | Contact discovery | Persona first: names and titles come from the company's own pages and from public search (Tavily). The email is then found by name and domain |
| 6 | Email finding | Waterfall: finders (Hunter, ZeroBounce) run in order, and each result is verified before the next is tried. A bake-off picks the chain. OrbiSearch has no finder API, so it is a verifier only |
| 7 | Verification | Only `valid` and `catch_all_resolved` addresses are safe to send. Other catch-alls go to a resolver; unresolved ones are held |
| 8 | Copy | Structured snippets (hook, relevance, value, ask) assembled by code. Body 50–85 words excluding the footer; follow-ups 25–50 words; reading grade ≤ 6.5; subject 2–5 lowercase words; no links in touch 1 |
| 9 | Cadence | Touches on business days 1, 4 and 9. Each follow-up is written just before it is due. Sends go out Tuesday to Thursday, 08:00–10:30, in the prospect's time zone |
| 10 | Mailbox | IMAP for now, with a Sent-folder sync. The sending gateway (EmailEngine, Smartlead or Instantly) is chosen before Phase 5 |
| 11 | Compliance | ISO country codes. UK leads need a confirmed incorporated company; DE and AT are blocked; CA needs a published or operator-given email; IN is held unless the operator gave the contact |
| 12 | Delivery order | Schema, then the engine on the CLI, then the API and web app |
| 13 | Budget | $0.50 ceiling per prospect, enforced before every paid call |

## 4. Research recommendations: verdicts

| # | Recommendation | Verdict | How we apply it |
|---|---|---|---|
| 1 | Plain status router outside; LangGraph inside Research and Copy | Adopt | The companies table is the resumable queue |
| 2 | Research supervisor with four workers | Adopt | The supervisor dispatches only the workers a lead needs: site and trigger, compliance and legal entity, campaign signals, and persona discovery (skipped if the operator gave a contact). Workers run in parallel |
| 3 | Copy actor-critic, at most 2 rewrites | Adopt | The critic runs the deterministic linter first, then an LLM specificity check |
| 4 | CLI and a read-only viewer before React | Adopt | Datasette during Phases 1–2 |
| 5 | Persona-first discovery | Adopt | Tavily over the company's pages and public search. Apollo free tier is optional |
| 6 | Waterfall with three finders and a verifier | Simplify | Any ordered chain is supported. The research's pay-as-you-go finder (OrbiSearch) has no API, so the candidates are Hunter and ZeroBounce, plus any cheaper API finder the bake-off adds |
| 7 | Safe-to-send gate; split email statuses | Adopt | Part of schema v1 |
| 8 | Catch-all resolvers | Adopt | Scrubby first (pay per use, 24–72 h); Enrichley as the real-time alternative |
| 9 | Never email guessed permutations; cache each domain's pattern | Adopt | `companies.email_pattern` |
| 10 | Bounce breaker: ≥3 hard bounces per 100 sends, or ≥2 in 24 h | Adopt | Hard and soft bounces are handled separately |
| 11 | Copy limits, snippet structure, subject rules, no links in touch 1 | Adopt | Configurable defaults enforced by the linter |
| 12 | Days 1/4/9, just-in-time follow-ups, send window | Adopt | Stored per campaign |
| 13 | Sent-folder sync for real Message-ID and send time | Adopt | Phase 2, over IMAP |
| 14 | EmailEngine, or Smartlead/Instantly | Defer | Chosen before Phase 5, behind the mailbox port |
| 15 | ISO countries, UK legal entity, DE/AT block, CASL provenance, DPDP | Adopt | Columns in schema v1; a lawyer confirms the policy values |
| 16 | Clay patterns: fit gate before paid enrichment, research questions, company/person tables, LinkedIn dedup, waterfall inspector | Adopt | Fits schema v1 with no extra tables |
| 17 | Manual, discovered and effective columns for every field, plus a history table | Simplify | Child rows for facts that can have several values; `manual_fields` protects operator input; every change is an event |
| 18 | Sparse intake with a domain resolver | Adopt | Through `import_rows` |
| 19 | Reply triage into six categories | Adopt | Phase 4 |
| 20 | Learning from operator edits | Adopt | Generated and final bodies are stored; recent edits in the campaign become few-shot examples for the copywriter |
| 21 | Positive-reply webhook, forget endpoint, DNS and warm-up preflight | Adopt | Phases 4–5 |
| 22 | Inbound intake webhook | Adopt | Signed `POST /api/intake/webhook` in Phase 3 |

## 5. Architecture

The engine is a modular monolith: one Python package, `outbound/`. It replaced the legacy `agent/` package, which is deleted after the first live run (the last step of Phase 2).

```
 CLI (Typer)     API (FastAPI) + Worker      Scheduler tick (cron)
        \                   |                        /
         +----------- Services (use cases) ---------+
                            |
                         Runner  -- picks companies by status, guards, commits each lead
                            |
   Stage handlers: Intake · Research* · Gate · Contacts · Email · Copy* · Review · Deliver · Sync
                            |                                   (* = LangGraph subgraph inside)
        +-------------------+---------------------+
   Domain core          Repositories          Provider ports (Metered: cache, caps, cost)
   (no I/O)             + unit of work               |
                            |                  Adapters: Tavily, finders, verifiers,
                     SQLite → Postgres          resolver, LLM, IMAP / gateway
```

**Package layout**

```
outbound/
  domain/      entities, enums, state machines, policies (compliance, safe-to-send, fit gate),
               contact ranking, copy linter, footer, edit distance — no I/O
  db/          SQLAlchemy models, Alembic migrations, repositories (including reports), unit of work
  providers/   ports (Protocols), adapters, registry, and the meter (metered.py, budget.py, pricing.py)
  prompts/     every instruction given to a model, one module per role
  stages/      one handler per stage; research/ and copy/ hold LangGraph subgraphs; email/ holds the
               waterfall and the catch-all poller; sync.py is the Sent-folder sync
  runner/      the status runner, its guards, and the tick
  services/    use cases shared by CLI and API: intake, review, leads, runs, settings, reports,
               webhook, forget, seed, legacy import
  api/         FastAPI app, auth, routers and schemas
  cli/         Typer commands
  config.py    pydantic-settings; secrets come from the environment only
  bootstrap.py builds the engine and unit-of-work factory once
  pipeline.py  wires stages to metered providers (real ones, or fakes in tests)
  worker.py    executes runs queued by the API
web2/          React app (served from web2/dist); its API client is generated from the OpenAPI document.
web/           the first React app, kept until it is deleted
```

**How one lead moves.** The runner reads a company due in a stage's input status, runs the guards (suppression, country policy after the gate, per-prospect budget), then calls the stage with no transaction open. The stage may call vendors (always through the meter) and returns a `StageResult`: the next status, engine-written fields, and any child rows to add. The runner writes all of it in one short transaction that checks `row_version`. A failure is recorded on the company with its stage and error, and the run moves on.

**Patterns**

| Pattern | Where | Why |
|---|---|---|
| Ports and adapters (Strategy) | `providers/` | Swapping a vendor means a new adapter and a config line |
| Chain of responsibility | Email waterfall | Each finder tries in turn; verification decides whether to stop |
| Decorator | `Metered*` wrappers (one per port) around a shared `Meter` | Cache, spend cap and cost record live in one place; a stage holds an ordinary port |
| Repository and unit of work | `db/` | Stages never see SQL; each lead gets one short transaction |
| State machine (transition table) | `domain/` | Illegal transitions are impossible, and each transition emits an event |
| Policy objects | compliance, safe-to-send, fit gate | Rules can be tested without a database |
| Command | stage handlers behind one `Stage` protocol, returning a `StageResult` | The runner treats every stage the same way and does all the writing |
| Composition root with constructor injection | `bootstrap.py` | No globals; tests inject fakes |

**Two hard contracts**

1. No database transaction stays open across a network call.
2. Every paid call commits its own `provider_calls` row, so its cost is recorded even if the stage then fails.

**Deliberately not used:** Celery, Redis or any queue (status plus `next_action_at` is the queue, and the worker polls the `runs` table for runs the API queued), an event bus, CQRS, microservices, a plugin framework, and generic base-repository hierarchies.

**Stack:** Python 3.12 managed with `uv`; SQLAlchemy 2 and Alembic; Pydantic v2 and pydantic-settings; httpx and tenacity; LangGraph (Research and Copy only); Typer; FastAPI and Uvicorn; argon2-cffi and itsdangerous (login); dnspython (mailbox DNS check); structlog logs (JSON, one request id per HTTP request, redaction of secrets and personal data; see CLAUDE.md and the manual, section 13a); tldextract; UUIDv7; pytest, ruff and mypy; pre-commit; GitHub Actions running on SQLite and Postgres. The web app uses React, TypeScript and Vite, with Tailwind, TanStack Query and Router, small hand-written components in the shadcn style, a client generated by openapi-typescript and openapi-fetch, and Playwright for the browser test.

## 6. Schema

Schema v1 has 17 tables in five areas. The company row is the lead. See [SCHEMA.md](SCHEMA.md).

| Area | Tables |
|---|---|
| Tenancy and configuration | `workspaces`, `campaigns`, `mailboxes`, `country_policies`, `suppressions` |
| Intake | `import_batches`, `import_rows` |
| Accounts and people | `companies`, `contacts`, `contact_emails`, `notes`, `consents` |
| Outreach | `messages`, `inbound_messages` |
| Runs, cost and audit | `runs`, `provider_calls`, `events` |

## 7. Lifecycles

**Company status** (the runner routes on this alone)

| Status | Meaning | Moves to |
|---|---|---|
| `new` | Passed intake with a confirmed domain | `researched`, `failed` |
| `researched` | People, country, legal entity, answers and fit score saved | `qualified`, `disqualified`, `held` |
| `qualified` | Passed the fit gate and the country policy | `contacts_found`, `held`, `failed` |
| `disqualified` | Fit below the campaign minimum. Manual leads bypass this gate, but the score is still recorded | `qualified` on operator override |
| `contacts_found` | 2–3 people ranked against the target titles | `email_ready`, `held`, `failed` |
| `email_ready` | The top usable contact has a safe-to-send email | `copy_ready`, `held` |
| `held` | Waiting on someone; `hold_reason` says why | The status it was held from |
| `copy_ready` | Touch 1 passed the linter or was flagged for review | `approved`, `rejected` |
| `approved` | An operator approved touch 1 | `in_sequence`, `held` |
| `in_sequence` | Touch 1 drafted or sent; follow-ups scheduled | `replied`, `completed`, `contacts_found`, `suppressed` |
| `replied` / `completed` / `rejected` / `suppressed` | Final states | — |
| `failed` | A stage error; `failed_stage` and `last_error` are stored | That stage's input status, on retry |

A hard bounce or a referral sends an `in_sequence` lead back to `contacts_found`. Country policy is checked again before every draft or send.

Two rules come from the transition tables in `outbound/domain/state_machines.py`:

- **Releasing a hold** resumes at the stage that held it, fixed by `hold_reason`: `catch_all_resolving` and `catch_all_unverified` go back to `contacts_found`; `consent_required`, `country_unknown` and `entity_unknown` go back to `researched`; `needs_operator` has no default, so the operator chooses.
- **A retry after `failed`** restores the input status of the stage that failed. Only research, gate, contacts, email and copy can fail a lead. Deliver and sync leave the lead where it is and try again an hour later.
- **Back-off.** A failed lead waits 15 minutes times the number of attempts so far before `outbound tick` retries it, and is retried automatically at most 3 times. The operator can retry at once from the CLI or the lead page.
- **A hold can start at `qualified`, `email_ready` and `approved` too.** If the country rules change after approval, or delivery finds the email is no longer safe (an opt-out, a bounce, a suppressed address), the lead is held with the reason and its approved email is withdrawn; once released it is checked again and gets a fresh first email. Nothing is retried silently.
- **Guards before every stage.** A suppressed domain, or a country that now blocks, moves the lead to `suppressed`. A policy that now needs a person holds the lead where the lifecycle allows a hold, and otherwise defers it. A lead that has used its per-prospect budget fails with that reason.

**Message state:** `generated → approved | rejected → drafted → sent → bounced`. A message can become `cancelled` at any point before it is sent. In Phases 2–4, `sent` is set by the Sent-folder sync.

**Email status:**

| Status | Safe to send? |
|---|---|
| `valid` | Yes |
| `catch_all_resolved` | Yes |
| `unverified` | No |
| `catch_all_pending` | No — the resolver is working; the lead is held as `catch_all_resolving` |
| `catch_all_unverified` | No — held unless `safe_to_send_only` is turned off |
| `unknown` | No |
| `invalid` | No, and never retried |

## 8. Pipeline stages

| Stage | Moves | What it does | Paid calls |
|---|---|---|---|
| 1 Intake | import row → `new` | A service, not a runner stage: called by `outbound targets`, the Targets screen and the webhook. Resolves the anchor to a root domain, normalises, deduplicates, checks suppression, and keeps operator notes and priority. Searches happen before the transaction; one transaction writes the batch | Tavily, only for rows with no domain |
| 2 Research (LangGraph) | `new` → `researched` | A supervisor dispatches up to four workers. **Site and trigger:** home, about, team and news pages. **Compliance and legal entity:** ISO country; UK incorporation from the site footer, then Companies House. **Campaign signals:** the campaign's research questions plus hiring and tech-stack signals. **Persona discovery:** people with titles and LinkedIn URLs from the team page, or one public LinkedIn-title search if there is none; skipped if the operator gave a contact. Then fit is scored with a reason. The legal-entity worker is plain code, not a model | 2–4 Tavily credits, 1–4 LLM calls |
| 3 Gate | `researched` → `qualified` / `disqualified` / `held` | Applies the campaign fit minimum (manual leads bypass it) and the country policy | — |
| 4 Contacts | `qualified` → `contacts_found` | Ranks the people found against the target titles, then by seniority; an operator-given person is rank 1. Research has already made the one public search, so this stage spends nothing; with nobody to rank, the lead fails with a reason | — |
| 5 Email | `contacts_found` → `email_ready` / `held` | Per contact, top 3: an address already held, then one published on the company site that fits the person, then the cached pattern (one address), then each finder in order, verifying every result. Invalid: next finder, then next contact. Catch-all: sent to the resolver. The chosen address's provenance is checked against the country policy before the lead moves on | Finder, verifier and resolver credits |
| 6 Copy (LangGraph) | `email_ready` → `copy_ready` | Writes snippet JSON using recent operator edits as examples, assembles it, and adds the country footer rendered from the sender profile (a blank field the footer needs fails the lead before any model call). The linter and a specificity check allow up to 2 rewrites; a draft that still fails goes to review flagged | 1–6 LLM calls |
| 7 Review | `copy_ready` → `approved` / `rejected` | By CLI (`outbound review`) or the web review queue. Edits are stored next to the generated text with their edit distance; an edit that removes the footer is refused | — |
| 8 Deliver | `approved` → `in_sequence` | Re-checks the full safe-to-send rule, then drafts over IMAP (Phases 2–4) or sends through the gateway within the send window (Phase 5). The draft's Message-ID is derived from the message and the mailbox is checked first, so a crash cannot leave a duplicate draft | Mailbox |
| 9 Sync and watch | `in_sequence` → final status, or back to `contacts_found` | **Sent sync:** Message-ID, send time and final body. **Inbox:** each message is classified; the next touch is scheduled and written just in time | LLM classifier, only when headers are not enough |

Cross-cutting rules:

- One failing lead never stops a run.
- A rerun repeats no paid call.
- Follow-ups are not drafted automatically until Phase 4.
- Due work is driven by `next_action_at`.
- Work that is not a stage runs as a **tick job**: the catch-all poller (releases leads held as `catch_all_resolving` when the resolver answers) and the Sent sync. `outbound tick` runs retries, then the jobs, then the pipeline.

## 9. Intake

| Anchor | Resolution | Stages skipped |
|---|---|---|
| Domain or website | Reduced to the registrable root domain | None |
| Company name, optionally with country or notes | One Tavily search for the official domain. If confidence is below 0.8, the row waits as `needs_confirmation` | None, once confirmed |
| Contact email | Domain taken from the address; stored as `operator_given`. A free-mail address is accepted only with `allow_personal_domain` | Email finding (the address is still verified) |
| Person and company | Company resolved as above; the person is stored at rank 1 | Persona search |
| LinkedIn profile URL | Stored, never scraped. A public search on the profile slug fills in name, title and company | Persona search |

Channels:

- **Phase 2:** CLI (CSV/XLSX file, `--company`, `--validate-only`).
- **Phase 3:** web quick-add, file upload with preview, domain confirmation, editing saved targets, and the signed intake webhook.

Modes are `manual`, `discovery` and `mixed`. Suppression always wins. A re-submitted domain merges into the existing company: notes are appended, and conflicting values become events.

## 10. Frontend (Phase 3)

| Screen | Purpose |
|---|---|
| Review queue | Generated email shown next to the research and the lint report; edit, approve or reject (edits are captured) |
| Targets | Quick add from any anchor, upload with preview, confirm domains, edit saved targets, assign a campaign |
| Leads | Filter by status or hold reason; timeline from `events`; waterfall inspector from `provider_calls`; operator and engine values side by side |
| Guided tour | First-visit walkthrough of every screen: Next, Back, Skip section, End tour; restart from the header. Steps are data in `web2/src/tour/steps.ts`; kept current by a rule in CLAUDE.md and an e2e test (`web2/e2e/tour.spec.ts`) |
| Lead page | Edit, add a person (with consent), record consent, suppress, delete (typed domain, refused once emailed), release. A release of a country-rule hold is refused while the cause is unchanged, so a lead never loops through the same hold |
| Lead journey | One lead's story: origin (import row and batch), eight stages with state, details, incidents and vendor calls, built by `services/journey.py` from existing rows; read-only (`GET /api/companies/{id}/journey`), no schema change |
| Runs | Start, watch or cancel a run; spend against budget |
| Settings | Sender profile, campaigns, country policies, suppression list, mailbox with DNS check |
| Replies (Phase 4) | Inbound messages by category, suggested answers, export of positive replies |

Rules:

- No business rules in the browser.
- Every write sends the `row_version` it read; a stale one gets HTTP 409.
- The API client is generated from OpenAPI (`npm run gen:api`); CI fails if it is out of date.
- One local login until Phase 6: an Argon2 hash in `OPERATOR_PASSWORD_HASH`, a signed HTTP-only SameSite=Strict cookie, and an `X-Requested-With` header on every write. Failed logins are throttled.
- Errors are problem-details responses (RFC 9457) with stable codes.
- The API never runs the pipeline in a request: it queues a run and `outbound worker` executes it.
- FastAPI serves the built app, so production is two processes: `outbound serve` and `outbound worker`.
- Deployment ([DEPLOY.md](DEPLOY.md)): one Docker image, run as three containers (`migrate`, `api`, `worker`) in the compose project `outbound` on a shared GCP VM. The VM builds the image. A manual GitHub Actions workflow deploys any commit over SSH, given the host and user, and rolls back to the previous release if `/api/health` fails. Secrets come from Doppler at container start (`doppler run`), the database is Supabase Postgres through its session pooler (`DATABASE_BACKEND` switches between local SQLite and Postgres) (the move planned for Phase 6, without its auth and row-level security yet), and the VM's existing reverse proxy terminates https in front of a loopback-only port. uvicorn trusts `X-Forwarded-For` (`FORWARDED_ALLOW_IPS`), so the login throttle sees real clients.

## 11. Compliance and deliverability

These summarise the research. They are not legal advice: a lawyer confirms the policy table before automatic sending is switched on.

| ISO | Rule | Engine behaviour |
|---|---|---|
| US | CAN-SPAM opt-out regime | `allow_with_footer`: sender identity, postal address, opt-out |
| GB | PECR: corporate subscribers (Ltd, PLC, LLP) only | Allowed only when `legal_entity_type = corporate_subscriber`; otherwise held. Footer includes registration details and data source |
| DE, AT | UWG §7: prior consent required, even B2B | `block`, unless a consent record exists |
| FR, NL, IE, SE | B2B legitimate interest | `allow_with_footer`, once a lawyer has reviewed the country |
| Other EU | Varies | Held until reviewed |
| CA | CASL: implied consent via conspicuous publication | Only with `publicly_published` or `operator_given` provenance |
| IN | DPDP: consent-based | Held unless consent is recorded (for example, an expo card) |
| Unknown | — | Held as `country_unknown` |

Operator tasks: keep a legitimate-interests assessment on file, name a grievance contact for India, and record every consent with its evidence.

**Deliverability**

- Use a separate sending domain.
- Preflight before the send switch can be turned on: SPF valid with at most 10 lookups, DKIM resolves, DMARC set to `quarantine` or `reject` with `rua`, domain isolation, and 14–21 days of warm-up.
- Daily cap ramps from 10–20 to about 50 over roughly four weeks.
- Send window as in decision 9, with 45–120 s random gaps (drafts have none).
- Plain text, no tracking, no links in touch 1.
- Breaker: ≥3 hard bounces per 100 sends, or ≥2 in 24 h. A soft bounce is retried once after 48 h.

## 12. Providers and cost

The research estimated about $0.06–0.07 per prospect plus LLM tokens, but that assumed a cheap pay-as-you-go finder. The vendors' own docs show no such finder API: **OrbiSearch is verify-only, and ZeroBounce's finder costs 20 credits (about $0.16) per address found.** The $0.50 ceiling should still hold, at roughly $0.17–0.20 per prospect with ZeroBounce finding and a cheap verifier, but the cost of the finding step is now the number to beat. The Phase 0 bake-off measures real accuracy and cost per safe email, and also tests other API finders (Anymail Finder and Findymail advertise one; neither is evaluated yet).

| Role | Candidates | Pricing (vendor pages, 2026-10-16) |
|---|---|---|
| Search, research, persona | Tavily Free | 1,000 credits/month; about 3–4 per prospect |
| Finder | Hunter, ZeroBounce | Hunter: 50 free credits/month, then a monthly plan. ZeroBounce: 20 credits per address found; unknown results are free |
| Verifier | MyEmailVerifier, OrbiSearch, ZeroBounce, Hunter | MyEmailVerifier: 100 free/day, then $0.0025. OrbiSearch: $0.0002 (0.2 credit), repeat checks free for 24 h. ZeroBounce: $0.008 |
| Catch-all resolver | Scrubby first; Enrichley if real time is needed | Scrubby: 200 free credits, price otherwise not public; its public docs are partial. Enrichley: from $59 per 5,000 credits |
| LLM | Any OpenAI-compatible endpoint: Anthropic (default), OpenAI, Gemini, Ollama, GitHub Copilot, or a custom host | Per token; prices per model in `LLM_PRICES` |
| UK registry | Companies House | Free, rate-limited; optional (without it, UK leads rely on incorporation markers on the site) |

Default prices live in `outbound/providers/pricing.py` and can be overridden with `PROVIDER_PRICES`; monthly caps per provider are set with `MONTHLY_CAPS_MICRO_USD`; the per-prospect ceiling is the workspace setting `budget_per_prospect_micro_usd`. The meter refuses a call before it would cross a cap and records the refusal.

## 13. Delivery phases

| Phase | Scope | Gate |
|---|---|---|
| [0 Fix and bake-off](phases/phase-0-fix-and-bakeoff.md) | Stop duplicate drafts, repo hygiene, provider ports and adapters, vendor bake-off | A rerun makes no duplicate drafts; the waterfall chain is chosen from data |
| [1 Schema and persistence](phases/phase-1-schema-and-persistence.md) | 17 tables, migrations, repositories, state machines, policy seeds, legacy import | Migrations pass on SQLite and Postgres; the 10 xlsx rows are imported |
| [2 Engine on the CLI](phases/phase-2-engine-on-cli.md) | Providers, runner, all stages through drafting, Sent sync | 8 of 10 emails sent without edits; a rerun makes zero paid calls |
| [3 API and web app](phases/phase-3-api-and-web-app.md) | FastAPI, React app, intake webhook | Nothing reaches the mailbox without approval in the web app |
| [4 Close the loop](phases/phase-4-close-the-loop.md) | Follow-ups, reply triage, bounces, referrals, opt-outs, forget, reply webhook | A reply stops the sequence; a referral becomes a new contact |
| [5 Automated sending](phases/phase-5-automated-sending.md) | Gateway, send window, breaker, preflight | Switch turns on only after gates 2 and 4, warm-up, and legal sign-off |
| [6 SaaS-ready](phases/phase-6-saas-ready.md) | Supabase Postgres, auth, row-level security | A second workspace runs with no data crossover |

## 14. Testing and quality bar

- **No network calls in CI.**
- **Layers tested:**
  - schema (migrations up and down on SQLite and Postgres; every constraint);
  - domain (every allowed and disallowed transition; policy per ISO code; linter);
  - repositories (workspace scoping, `manual_fields`, `row_version`, forget);
  - providers (Metered cache, caps and cost; adapters against recorded responses);
  - stages (waterfall order, catch-all path, intake anchors);
  - runner (kill and rerun);
  - mailbox fixtures (Sent matching, reply categories);
  - the whole pipeline end to end with fake vendors (targets to draft, rerun at zero cost);
  - API (every endpoint, auth, the 409 conflict, webhook signature and replay);
  - the browser loop (Playwright against a real server and worker with fake vendors).
- **Copy gate:** 8 of 10 touch-1 emails sent without edits, measured automatically by comparing `generated_body` with the body the Sent sync finds.
- **Enrichment gate:** the share found, the share verified safe, wrong answers, and cost per safe email over 30 known contacts.
- **Code gate:** ruff and mypy clean (strict on `domain`), typed public APIs, CI green before merge.

## 15. Risks

| Risk | Mitigation |
|---|---|
| Vendor figures differ from the research | Bake-off first; every vendor sits behind one port |
| Many catch-alls stay unresolved | The resolver handles most; the held share is tracked from Phase 2 |
| Public LinkedIn search is still personal data | Legitimate-interests assessment, no scraping, a forget action |
| The Sent sync matches the wrong message | Match on recipient, subject and time window; an ambiguous match holds the follow-up |
| UK legal-entity detection misses a company | Companies House as a second source; operator can confirm by hand |
| A country rule is misread | Lawyer review before Phase 5; anything unknown is held |
| Scope creep | Deferred items stay deferred until a measured need appears |
