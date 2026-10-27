# Outbound Engine — End-to-End Plan

**Status:** approved by the team on 2026-10-16. Every decision below is final.
**Build status (2026-10-18):** Phases 0–3 are code complete and tested with fake vendors; their gates wait on live runs with real keys. See [phases/README.md](phases/README.md). Where the build differs from the original wording, the text below has been updated and each phase document lists the differences.
**SaaS (2026-10-23):** the team approved an invite-only SaaS alpha, Phase 6, split into 6a–6g. Its overview is [phases/phase-6-saas-ready.md](phases/phase-6-saas-ready.md); decisions 14–22 below summarise it.
**Where it lives:** this file is the source of truth for building the engine. The team reviewed the
[plan in Claude Docs](https://claude.ai/code/artifact/4cea76e3-1e09-442e-a719-22299ed78ece); any later change is made here, in the same PR as the code it affects.

Related documents:

- [technical/](technical/README.md) is the engineering documentation: architecture, HLD, per-module LLDs, decision records (ADRs), data, API, integrations, security and privacy, operations and runbooks. It is the source of truth for *how* the system is built; this plan stays the source for *what* it does and *why*.
- [technical/data/schema.md](technical/data/schema.md) is the column-level spec for schema v1.
- [phases/](phases/README.md) holds one document per delivery phase, with tasks, files and exit gates.
- [archive/](archive/README.md) keeps the superseded specs and notes, for history only.

---

## 1. Summary

The engine accepts or finds target companies, researches each one, finds and verifies a decision-maker's email, writes a short personalised email, and drafts it in the mailbox once a human approves it. Later phases add reply handling, follow-ups and automatic sending.

Phase 6 turns the engine into a multi-tenant product, starting with an invite-only alpha:
- each customer has its own workspace, team, mailboxes and limits;
- platform admins have a console;
- a shared, verified lead directory cuts vendor cost.

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
- Later: follow-ups, reply handling, automatic sending.
- **SaaS alpha (Phase 6):**
  - invited companies, each isolated in its own workspace;
  - per-step credits set by platform admins;
  - vendor keys owned by the platform;
  - a shared, verified lead directory checked before any paid vendor.

**Non-goals**

- A CRM. Positive replies go out to one by webhook or export.
- In the alpha: payments, MFA, social sign-in and SSO (see Phases 6e and 6f).
- Any channel other than email.
- LinkedIn scraping. Only public search results are read.
- Open or click tracking.

## 3. Decisions (all confirmed)

| # | Decision | Choice |
|---|---|---|
| 1 | Users | One operator until Phase 6. Then an invite-only multi-tenant alpha: one company = one workspace (decisions 14–22) |
| 2 | Store | SQLite through SQLAlchemy 2 and Alembic for development and tests; Supabase Postgres in production, with row-level security and least-privilege roles from 6a; `workspace_id` on every tenant table |
| 3 | Orchestration | A plain Python runner moves each company through its statuses. LangGraph subgraphs run only inside Research and Copy |
| 4 | Targets | A lead can start from one anchor: domain, website, company name, email, person and company, or LinkedIn profile URL |
| 5 | Contact discovery | Persona first: names and titles come from the company's own pages and from public search (Tavily). The email is then found by name and domain |
| 6 | Email finding | Waterfall: finders (Hunter, ZeroBounce) run in order, and each result is verified before the next is tried. A bake-off picks the chain. OrbiSearch has no finder API, so it is a verifier only |
| 7 | Verification | Only `valid` and `catch_all_resolved` addresses are safe to send. Other catch-alls go to a resolver; unresolved ones are held |
| 8 | Copy | The writer model returns the body as 2–4 paragraphs plus the subject and the url of the news item it opens with; code adds greeting, signature and footer. Body 120–200 words by default (a workspace setting), greeting, sign-off and footer excluded; follow-ups 25–50 words; reading grade ≤ 10; one or two questions; no bullet lists, at most one em dash, no stock or machine-sounding phrases; subject 2–6 lowercase words; no links in touch 1 |
| 9 | Cadence | Touches on business days 1, 4 and 9. Each follow-up is written just before it is due. Sends go out Tuesday to Thursday, 08:00–10:30, in the prospect's time zone |
| 10 | Mailbox | IMAP with a Sent-folder sync, from one mailbox in `.env`, until 6c. From 6c, each workspace connects its own mailboxes in Settings: Microsoft 365 (Graph, OAuth), Google (Gmail API, OAuth) or any IMAP account (app password). Phase 5 sends through the same adapters, so no separate gateway |
| 11 | Compliance | ISO country codes. UK leads need a confirmed incorporated company; DE and AT are blocked; CA needs a published or operator-given email; IN is held unless the operator gave the contact |
| 12 | Delivery order | Schema, then the engine on the CLI, then the API and web app |
| 13 | Budget | $0.50 ceiling per prospect, enforced before every paid call. From 6d, a plan can lower its maximum, and "no limit" is not allowed |
| 14 | Tenancy (2026-10-23) | Shared database and schema. Composite foreign keys. Postgres row-level security under `outbound_app`. Cross-workspace reads by `outbound_platform` without BYPASSRLS. The owner is used only to migrate. See [phase 6a](phases/phase-6a-tenancy-foundation.md) |
| 15 | Sign-in | Email and password (Argon2id), invitations, password reset, server-side sessions, behind an `IdentityProvider` port. No MFA, social sign-in or SSO in the alpha ([6b](phases/phase-6b-identity-and-access.md)). Platform staff may invite someone to Outbound with no workspace; that person makes a workspace (and is its admin) or asks to join one with its join code, and any admin of it approves or rejects, told by an in-app notification (6h, migration 0017) |
| 16 | Roles | Fixed RBAC. Workspace roles `admin` and `member`. Platform roles `admin` and an alpha-only `superadmin`, who reads every workspace. Every route declares its permission |
| 17 | Plans and credits | Credits per pipeline step, charged once per lead. The free plan allows 5 discovered + 5 manually added leads a month. Admins set any limit, grant credits and extend access. A lead stopped by a limit waits in place and resumes when credits exist ([6d](phases/phase-6d-plans-limits-and-admin.md)) |
| 18 | Vendor keys | Owned by the platform, stored encrypted in the database from 6d, and seen and replaced by admins in the console without a restart |
| 19 | LLM | DeepSeek served by DeepInfra (OpenAI-compatible), replacing OpenRouter |
| 20 | Admin console | `/admin`, nine screens: customers, limits and credits, users, plans, vendors and keys, directory, settings, audit log |
| 21 | Lead directory | Shared verified facts (companies, people, LinkedIn profiles, emails), all shareable in the alpha. It is the free first link of the email waterfall, and customers may skip it when an admin allows ([6g](phases/phase-6g-lead-directory.md)) |
| 22 | Payments | None in the alpha. Staff assign plans. Billing is [6e](phases/phase-6e-billing.md), after the alpha |

## 4. Research recommendations: verdicts

| # | Recommendation | Verdict | How we apply it |
|---|---|---|---|
| 1 | Plain status router outside; LangGraph inside Research and Copy | Adopt | The companies table is the resumable queue |
| 2 | Research supervisor with four workers | Adopt | The supervisor dispatches only the workers a lead needs: site and trigger, compliance and legal entity, campaign signals, and persona discovery (skipped if the operator gave a contact). Workers run in parallel |
| 3 | Copy actor-critic, at most 2 rewrites | Adopt | The critic runs the deterministic linter and the source check first (the opening news item must be one research found, and recent news must be used when there is some), then one model check: every fact grounded, and it reads like a person wrote it. A rewrite sees its last draft and the problems |
| 4 | CLI and a read-only viewer before React | Adopt | Datasette during Phases 1–2 |
| 5 | Persona-first discovery | Adopt | Tavily over the company's pages and public search. Apollo free tier is optional |
| 6 | Waterfall with three finders and a verifier | Simplify | Any ordered chain is supported. The research's pay-as-you-go finder (OrbiSearch) has no API, so the candidates are Hunter and ZeroBounce, plus any cheaper API finder the bake-off adds |
| 7 | Safe-to-send gate; split email statuses | Adopt | Part of schema v1 |
| 8 | Catch-all resolvers | Adopt | Scrubby first (pay per use, 24–72 h); Enrichley as the real-time alternative |
| 9 | Never email guessed permutations; cache each domain's pattern | Adopt | `companies.email_pattern` |
| 10 | Bounce breaker: ≥3 hard bounces per 100 sends, or ≥2 in 24 h | Adopt | Hard and soft bounces are handled separately |
| 11 | Copy limits, subject rules, no links in touch 1 | Adopt | Defaults enforced by the linter; the first-email length is a workspace setting |
| 12 | Days 1/4/9, just-in-time follow-ups, send window | Adopt | Stored per campaign |
| 13 | Sent-folder sync for real Message-ID and send time | Adopt | Phase 2, over IMAP |
| 14 | EmailEngine, or Smartlead/Instantly | Superseded (2026-10-23) | Each workspace connects its own mailbox (6c), and Phase 5 sends through that adapter. EmailEngine stays an option if many IMAP connections become a burden |
| 15 | ISO countries, UK legal entity, DE/AT block, CASL provenance, DPDP | Adopt | Columns in schema v1; a lawyer confirms the policy values |
| 16 | Clay patterns: fit gate before paid enrichment, research questions, company/person tables, LinkedIn dedup, waterfall inspector | Adopt | Fits schema v1 with no extra tables |
| 17 | Manual, discovered and effective columns for every field, plus a history table | Simplify | Child rows for facts that can have several values; `manual_fields` protects operator input; every change is an event |
| 18 | Sparse intake with a domain resolver | Adopt | Through `import_rows` |
| 19 | Reply triage into six categories | Adopt | Phase 4 |
| 20 | Learning from operator edits | Adopt | Generated and final bodies are stored; recent edits in the campaign become few-shot examples for the copywriter |
| 21 | Positive-reply webhook, forget endpoint, DNS and warm-up preflight | Adopt | Phases 4–5 |
| 22 | Inbound intake webhook | Adopt | Signed `POST /api/intake/webhook/{workspace_id}` (Phase 3; one URL and one encrypted secret per workspace from 6c, made in Settings → Integrations) |

## 5. Architecture

> **Moved.** The architecture is now described in [technical/architecture/architecture.md](technical/architecture/architecture.md) (arc42 and C4 views, the technology stack, the package layout) and [technical/hld/hld.md](technical/hld/hld.md) (processes, the queue, the multi-tenant worker, tenancy and row-level security, integrations, limits). The decisions behind it are recorded as [ADRs](technical/adr/README.md).

The engine is a modular monolith: one Python package, `outbound/`, in layers that import only downward ([ADR 0001](technical/adr/0001-modular-monolith.md)). It replaced the legacy `agent/` package, deleted after the first live run. A plain Python runner moves each company through its statuses; LangGraph runs only inside research and copy ([ADR 0004](technical/adr/0004-langgraph-only-in-research-and-copy.md)). The companies table is the queue ([ADR 0002](technical/adr/0002-the-table-is-the-queue.md)); from 6a, the worker serves every workspace fairly and the platform-wide view (what is due, admin reads) goes through a separate `outbound_platform` connection that never sees a tenant's rows except what the scheduler needs to pick work ([the tenancy LLD](technical/lld/tenancy-and-isolation.md)).

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

Each pattern is also an [ADR](technical/adr/README.md); the LLD of the module names which one.

**Two hard contracts**

1. No database transaction stays open across a network call.
2. Every paid call commits its own `provider_calls` row, so its cost is recorded even if the stage then fails.

**Tenant context (Phase 6).** All of 6a–6d are built now; nothing below is still planned. Full detail, verified against the code, is in [technical/hld/hld.md §5](technical/hld/hld.md#5-tenancy), [technical/lld/tenancy-and-isolation.md](technical/lld/tenancy-and-isolation.md) and [technical/lld/identity-and-access.md](technical/lld/identity-and-access.md).
- **Workspace identity on every request:** the SPA sends `X-Workspace-Id`, taken from the `/w/{slug}` URL; the `tenant()` dependency (`api/deps.py`) checks the session, the membership and role (or a read-only superadmin view), and whether access has ended; it then builds that request's services for that workspace.
- **Unit of work:** every tenant unit of work is bound to one workspace, and a Session `after_begin` listener sets `app.workspace_id` in every transaction for Postgres row-level security (`outbound/db/session.py`).
- **Reads across workspaces** (the scheduler's "what is due", the admin console) go through `PlatformUnitOfWork` (`db/platform.py`), on its own `outbound_platform` connection, which has no row-level-security bypass and cannot write a tenant's rows; import-linter keeps tenant code (stages, the runner, services) from importing it.
- **Identity and sessions** (`db/identity.py`) — users, memberships, invitation and reset tokens, sessions, the audit log — are platform tables with no row-level security, reached only through named queries, never through tenant code.
- **The worker** claims runs for every workspace fairly (least-recently-served first, a thread pool), assembles a pipeline per run, ticks each active workspace every 15 minutes, and fails runs whose heartbeat stopped for 30 minutes.

**Deliberately not used:** Celery, Redis or any queue (status plus `next_action_at` is the queue, and the worker polls the `runs` table for runs the API queued), an event bus, CQRS, microservices, a plugin framework, and generic base-repository hierarchies.

**Stack:** Python 3.12 managed with `uv`; SQLAlchemy 2 and Alembic; Pydantic v2 and pydantic-settings; httpx and tenacity; LangGraph (Research and Copy only); Typer; FastAPI and Uvicorn; argon2-cffi and itsdangerous (login); dnspython (mailbox DNS check); structlog logs (JSON, one request id per HTTP request, redaction of secrets and personal data; see CLAUDE.md and the manual, section 13a); tldextract; UUIDv7; pytest, ruff and mypy; pre-commit; GitHub Actions running on SQLite and Postgres. The web app uses React, TypeScript and Vite, with Tailwind, TanStack Query and Router, small hand-written components in the shadcn style, a client generated by openapi-typescript and openapi-fetch, and Playwright for the browser test.

## 6. Schema

Schema v1 started at 17 tables in five areas; the SaaS tables bring it to 35. The company row is the lead. See [technical/data/schema.md](technical/data/schema.md) for every table, and [technical/data/migrations.md](technical/data/migrations.md) for how it got here.

| Area | Tables |
|---|---|
| Tenancy and configuration | `workspaces`, `campaigns`, `mailboxes`, `country_policies`, `suppressions` |
| Intake | `import_batches`, `import_rows` |
| Accounts and people | `companies`, `contacts`, `contact_emails`, `notes`, `consents` |
| Outreach | `messages`, `inbound_messages` |
| Runs, cost and audit | `runs`, `provider_calls`, `events` |

## 7. Lifecycles

Every lifecycle, copied from the code with a diagram, is in [technical/hld/state-machines.md](technical/hld/state-machines.md); the full layered safety model is in [technical/hld/safety-model.md](technical/hld/safety-model.md). This section keeps the product-level summary.

**Workspace status** (Phase 6a; `outbound/domain/enums.py::WorkspaceStatus`): `active` → `paused` (a platform admin stopped its engine; people can still sign in and read) or `suspended` (nobody can use it) → `pending_deletion` (restorable until due) → `deleted` (a tombstone; cost history keeps its key). A workspace past its plan's access date is `active` but read-only (a quota check, not a status).

**Company status** (the runner routes on this alone)

| Status | Meaning | Moves to |
|---|---|---|
| `new` | Passed intake with a confirmed domain | `researched`, `failed` |
| `researched` | People, country, legal entity, answers and fit score saved | `qualified`, `disqualified`, `held` |
| `qualified` | Passed the fit gate and the country policy | `contacts_found`, `held`, `failed` |
| `disqualified` | Fit below the campaign minimum. Manual leads bypass this gate, but the score is still recorded | `qualified` on operator override |
| `contacts_found` | 2–3 people ranked against the target titles | `email_ready`, `held`, `failed` |
| `email_ready` | The top usable contact has a safe-to-send email | `copy_ready`, `held`, `contacts_found` (operator picks someone else) |
| `held` | Waiting on someone; `hold_reason` says why | The status it was held from |
| `copy_ready` | Touch 1 passed the linter or was flagged for review | `approved`, `rejected`, `contacts_found` (operator picks someone else; the email is cancelled) |
| `approved` | An operator approved touch 1 | `in_sequence`, `held`, `contacts_found` (operator picks someone else; the email is cancelled) |
| `in_sequence` | Touch 1 drafted or sent; follow-ups scheduled | `replied`, `completed`, `contacts_found`, `suppressed` |
| `replied` / `completed` / `rejected` / `suppressed` | Final states | — |
| `failed` | A stage error; `failed_stage` and `last_error` are stored | That stage's input status, on retry |

A hard bounce or a referral sends an `in_sequence` lead back to `contacts_found`. Country policy is checked again before every draft or send.

Two rules come from the transition tables in `outbound/domain/state_machines.py`:

- **Releasing a hold** resumes at the stage that held it, fixed by `hold_reason`: `catch_all_resolving` and `catch_all_unverified` go back to `contacts_found`; `consent_required`, `country_unknown` and `entity_unknown` go back to `researched`; `needs_operator` has no default, so the operator chooses.
- **A retry after `failed`** restores the input status of the stage that failed. Only research, gate, contacts, email and copy can fail a lead. Deliver and sync leave the lead where it is and try again an hour later.
- **Back-off.** A failed lead waits 15 minutes times the number of attempts so far before a tick (the worker's, every 15 minutes, or `outbound tick`) retries it, and is retried automatically at most 3 times. The operator can retry at once from the CLI or the lead page.
- **A hold can start at `qualified`, `email_ready` and `approved` too.** If the country rules change after approval, or delivery finds the email is no longer safe (an opt-out, a bounce, a suppressed address), the lead is held with the reason and its approved email is withdrawn; once released it is checked again and gets a fresh first email. Nothing is retried silently.
- **Guards before every stage.** A suppressed domain moves the lead to `suppressed`. A country rule that now blocks or needs a person holds the lead (`needs_operator` for a block) where the lifecycle allows a hold, and otherwise defers it: a rule can come back into force (a skip revoked, the workspace switch turned back on), so it never ends a lead for good. A lead that has used its per-prospect budget fails with that reason.

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

**The operator can skip the check for one address** (`contact_emails.verification_skipped`, with a reason in the `email_verification_skipped` event): the address is then sendable whatever its status, even `invalid`, and no verifier or finder is called for it. Suppression still applies.

**Revisions on Review.** The operator can ask the writer model to rewrite a waiting email with free-text instructions (tone, length, facts to add; `POST /api/review/{id}/revise`). It revises the text as it stands in the editor, never sees or changes the footer (code puts it back), treats the operator's facts as true, and returns the text and its lint report without saving; approval stores it as the operator's version (`final_body`, with its edit distance). The request is recorded as a `revision_asked` event; the call goes through the meter, attributed to the lead.

**Approval confirms every skip.** An email that relies on a skipped check (the country rule skipped for the lead or switched off for the workspace, an address used without proof, or a person a search could not place and the operator confirmed) is approved only with an explicit acknowledgement (`acknowledge_skips`; the Review screen's tick box, or `--acknowledge-skips` on the CLI), recorded in an `approved_with_skips` event. Approval also refuses a suppressed address. **Automatic sending (Phase 5) must never send a message that relies on a skipped check**; such a message always waits for a person.

## 8. Pipeline stages

Sequence diagrams for every stage, with exact code citations, are in [technical/hld/pipeline-flow.md](technical/hld/pipeline-flow.md) and the stage [LLDs](technical/README.md#low-level-design). The email stage now checks the [verified lead directory](technical/lld/lead-directory.md) first (6g), and pipeline stages are now gated by [credits](technical/lld/plans-credits-and-admin.md) as well as by budget.

| Stage | Moves | What it does | Paid calls |
|---|---|---|---|
| 1 Intake | import row → `new` | A service, not a runner stage: called by `outbound targets`, the Targets screen and the webhook. Resolves the anchor to a root domain, normalises, deduplicates, checks suppression, and keeps operator notes and priority. Searches happen before the transaction; one transaction writes the batch | Tavily, only for rows with no domain |
| 2 Research (LangGraph) | `new` → `researched` | A supervisor dispatches up to four workers. **Site and trigger:** home, about, team and news pages. **Compliance and legal entity:** ISO country; UK incorporation from the site footer, then Companies House. **Campaign signals:** the campaign's research questions plus hiring and tech-stack signals. **Persona discovery:** people with titles and LinkedIn URLs from the team page (never from other sites' pages when the site could not be read), or one public LinkedIn-title search if there is none; skipped if the operator gave a contact. A searched person is *confirmed* only when their profile's employer is the company (its whole name or its website's name); one shared word is never enough. A person the result only mentions with the company is saved as `unconfirmed` and is not worked on until the operator confirms them; anyone else is dropped. The site worker runs first and returns the company's own name, which the engine saves (unless the operator set one) and the other workers search with. **News:** the site worker also names the company's sector; then two news searches run (Tavily `topic=news`): the company by name over the last 180 days and its market (`<sector>` with regulation, tender, funding, acquisition) over the last 90. Only dated hits that name the company are kept; the model picks up to 3 company items and 2 market triggers by number (headline, date and link always come from the search result, never from the model). A failed news search never fails the lead. News searches are cached for 7 days, other searches for 30. Then fit is scored with a reason. The legal-entity worker is plain code, not a model | 4–6 Tavily credits (two of them news searches), 2–5 LLM calls |
| 3 Gate | `researched` → `qualified` / `disqualified` / `held` | Applies the campaign fit minimum (manual leads bypass it) and the country policy | — |
| 4 Contacts | `qualified` → `contacts_found` | Ranks the people found against the target titles, then by seniority. A person the operator chose (added them, gave their address, or recorded their consent) comes first, in the order the operator left them. Research has already made the one public search, so this stage spends nothing; with nobody to rank, the lead fails with a reason | — |
| 5 Email | `contacts_found` → `email_ready` / `held` | Per contact, top 3: an address already held, then one published on the company site that fits the person, then the cached pattern (one address), then each finder in order, verifying every result. Invalid: next finder, then next contact. Catch-all: sent to the resolver. The chosen address's provenance is checked against the country policy before the lead moves on | Finder, verifier and resolver credits |
| 6 Copy (LangGraph) | `email_ready` → `copy_ready` | The writer model (`LLM_COPY_MODEL`, else `LLM_MODEL`) writes the body from a brief: open with the most recent dated news (company news, else a market trigger, else a site fact), say what it means for them, one relevant thing the sender has done, one clear ask fitting the sender's `outreach_goal`, in a person's voice. It sees the research, the operator's notes, recent operator edits, and up to four past emails of the operator's as voice reference (labelled not to be copied). Code adds the greeting (`sender_profile.greeting`), signature and the country footer (a blank field the footer needs fails the lead before any model call). The checks allow up to 2 rewrites; a draft that still fails goes to review flagged. `messages.snippets` keeps the subject, the source url and the news item it opened with, which Review shows | 2–6 LLM calls |
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
| Company name, optionally with country or notes | One Tavily search for the official domain. The website's name must hold the whole company name ("tatapower.com" for Tata Power, not the group's "tata.com"); if confidence is below 0.8, the row waits as `needs_confirmation` | None, once confirmed |
| Contact email | Domain taken from the address; stored as `operator_given`. A free-mail address is accepted only with `allow_personal_domain` | Email finding (the address is still verified) |
| Person and company | Company resolved as above; the person is stored at rank 1 | Persona search |
| LinkedIn profile URL | Stored, never scraped. A public search on the profile slug fills in name, title and company | Persona search |

Channels:

- **Phase 2:** CLI (CSV/XLSX file, `--company`, `--validate-only`).
- **Phase 3:** web quick-add, file upload with preview, domain confirmation, editing saved targets, and the signed intake webhook.

Modes are `manual`, `discovery` and `mixed`. Discovery searches for companies (not articles) matching the campaign's ideal customer, asks for twice the wanted count, skips articles and documents (`.pdf`, `/blog/`, `/news/`, `/insights/`, `/report/` and similar), and stores only the website and the page it was found on: a search result's title is never used as the company's name. Suppression always wins. A re-submitted domain merges into the existing company: notes are appended, and conflicting values become events.

## 10. Frontend (Phase 3)

| Screen | Purpose |
|---|---|
| Review queue | Generated email shown next to the research and the lint report; edit, approve or reject (edits are captured) |
| Targets | Quick add from any anchor, upload with preview, confirm domains, edit saved targets, assign a campaign |
| Leads | Filter by status or hold reason; timeline from `events`; waterfall inspector from `provider_calls`; operator and engine values side by side |
| Guided tour | First-visit walkthrough of every screen: Next, Back, Skip section, End tour; restart from the header. Steps are data in `web2/src/tour/steps.ts`; kept current by a rule in CLAUDE.md and an e2e test (`web2/e2e/tour.spec.ts`) |
| Lead page | Research again (back to `new`: research, gate, people, email and copy run again; a waiting or approved email is cancelled; operator values kept), edit (including a new address, kept beside the old one), add a person (with consent; the same name updates the existing person), record consent (once per basis), write to someone else (cancels the waiting email), remove a wrong match (refused once written to), suppress, delete (typed domain, refused once emailed), release. A release of a country-rule hold is refused while the cause is unchanged, so a lead never loops through the same hold |
| Lead journey | One lead's story: origin (import row and batch), eight stages with state, details, incidents and vendor calls, built by `services/journey.py` from existing rows; read-only (`GET /api/companies/{id}/journey`), no schema change |
| Runs | Start, watch or cancel a run; spend against budget |
| Settings | Sender profile, campaigns, country policies, suppression list, mailbox with DNS check |
| Replies (Phase 4) | Inbound messages by category, suggested answers, export of positive replies |
| Sign-in, invitations, onboarding (6b, 6c) | Public pages outside the app shell. A wizard: workspace details, company profile, sender identity, mailbox with DNS health, first campaign, first leads |
| Settings (6c onward) | Sections: Account (profile, password, sessions) and Workspace (general, company profile, mailboxes and senders, deliverability, compliance, team, plan and usage, integrations, data and privacy) |
| Admin console (6d) | `/admin` for platform roles: overview, customers (limits and credits, access, features, members, mailboxes, activity), users, plans, vendors and keys, directory, settings, audit log |

Rules:

- No business rules in the browser.
- Every write sends the `row_version` it read; a stale one gets HTTP 409.
- The API client is generated from OpenAPI (`npm run gen:api`); CI fails if it is out of date.
- Sign-in (Phase 6b): people sign in with an email and password (Argon2id, at least 15 characters) into server-side sessions the server can revoke. The cookie holds only a random token: HttpOnly, SameSite=Strict, and `__Host-` over https. Every write also carries an `X-Requested-With` header. Failed sign-ins are throttled per client and per account, and the answer never reveals whether an account exists.
- Accounts exist only by invitation: platform staff create a customer and invite its first admin (`POST /api/admin/customers`); workspace admins invite their own people. Invitation links last 7 days and reset links 30 minutes; both are single use and stored as hashes.
- Every request names its workspace in an `X-Workspace-Id` header (a person in one workspace may leave it out). Every route declares one permission (`require(...)` in `api/deps.py`); a test fails any route that declares none. App URLs carry the workspace (`/w/{slug}`).
- What a person does is recorded as `user:<id>`; the intake webhook as `integration:webhook`. Both count as operator input (rule 7).
- Errors are problem-details responses (RFC 9457) with stable codes.
- The API never runs the pipeline in a request: it queues a run and `outbound worker` executes it.
- FastAPI serves the built app, so production is two processes: `outbound serve` and `outbound worker`.
- Deployment: one Docker image, run as three containers (`migrate`, `api`, `worker`) in the compose project `outbound` on a shared GCP VM, reaching Supabase Postgres as the least-privilege `outbound_app` (and `outbound_platform` for the worker's cross-workspace reads) rather than the table owner. See [technical/operations/deployment.md](technical/operations/deployment.md) and [technical/operations/release-and-rollback.md](technical/operations/release-and-rollback.md).

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

**The operator can switch the country rules.** For one lead, `companies.policy_skip_from` skips the rule from a stage onward (`gate`, `contacts`, `email`, `copy`, `deliver`); a tail, never an arbitrary set, so no stage contradicts a later one. A lead the rule stopped resumes at the stage that stopped it; the skip can start there or earlier. For the workspace, `settings.country_policy_enabled` (default on) switches them all off. Either way the decision is ALLOW with `skipped` recorded, suppression still applies, and the footer follows `settings.footer_enabled` (default on): the country's footer, or a short default with the sender's address and an opt-out line. Every country-rule change, removal and skip is an event.

Consent belongs to a person. Before a recipient is chosen (the gate, the runner's guard), anyone's consent at the company keeps the lead moving; once the email, copy or deliver step names the recipient, only *that person's* consent counts, so someone else's consent never allows writing to them.

Operator tasks: keep a legitimate-interests assessment on file, name a grievance contact for India, and record every consent with its evidence.

**As a SaaS (Phase 6):**
- **Roles:** the platform is each customer's *processor*, and the customer is the controller of its prospects' data.
- **Before the first outside customer:** Terms, an Acceptable Use Policy, a Privacy Policy, a click-through DPA (GDPR Art. 28, with SCCs) that names the lead directory, and a sub-processor list (DeepInfra included).
- **Country rules** stay each customer's decision, starting from our defaults.
- **The lead directory (6g)** makes the platform its *controller*, and probably a data broker under some US laws. Before the public launch, counsel signs off on [6f](phases/phase-6f-launch-readiness.md):
  - a legitimate-interests assessment and a DPIA;
  - Art. 14 notices to each person;
  - US broker registration and California DROP;
  - vendor terms, Hunter's first.

**Deliverability**

- Use a separate sending domain.
- Preflight before the send switch can be turned on: SPF valid with at most 10 lookups, DKIM resolves, DMARC set to `quarantine` or `reject` with `rua`, domain isolation, and 14–21 days of warm-up.
- Daily cap ramps from 10–20 to about 50 over roughly four weeks.
- Send window as in decision 9, with 45–120 s random gaps (drafts have none).
- Plain text, no tracking, no links in touch 1.
- Breaker: ≥3 hard bounces per 100 sends, or ≥2 in 24 h. A soft bounce is retried once after 48 h.

## 12. Providers and cost

Each vendor's endpoints, mapping, prices, cache and live-check status are in [technical/integrations/](technical/integrations/README.md), including the two new mailbox gateways (Microsoft Graph, Gmail API) and the platform's own vendor-key store.

The research estimated about $0.06–0.07 per prospect plus LLM tokens, but that assumed a cheap pay-as-you-go finder. The vendors' own docs show no such finder API: **OrbiSearch is verify-only, and ZeroBounce's finder costs 20 credits (about $0.16) per address found.** The $0.50 ceiling should still hold, at roughly $0.17–0.20 per prospect with ZeroBounce finding and a cheap verifier, but the cost of the finding step is now the number to beat. The Phase 0 bake-off measures real accuracy and cost per safe email, and also tests other API finders (Anymail Finder and Findymail advertise one; neither is evaluated yet).

| Role | Candidates | Pricing (vendor pages, 2026-10-16) |
|---|---|---|
| Search, research, persona | Tavily Free | 1,000 credits/month; about 3–4 per prospect |
| Finder | Hunter, ZeroBounce | Hunter: 50 free credits/month, then a monthly plan. ZeroBounce: 20 credits per address found; unknown results are free |
| Verifier | MyEmailVerifier, OrbiSearch, ZeroBounce, Hunter | MyEmailVerifier: 100 free/day, then $0.0025. OrbiSearch: $0.0002 (0.2 credit), repeat checks free for 24 h. ZeroBounce: $0.008 |
| Catch-all resolver | Scrubby first; Enrichley if real time is needed | Scrubby: 200 free credits, price otherwise not public; its public docs are partial. Enrichley: from $59 per 5,000 credits |
| LLM | Any OpenAI-compatible endpoint: Anthropic, OpenAI, Gemini, Ollama, GitHub Copilot, or a custom host. **In use: DeepSeek served by DeepInfra** (`openai_compatible`; prompts held in memory only, no training, per DeepInfra's documentation) | Per token; prices per model in `LLM_PRICES` (3b B5: set them for the DeepSeek model) |
| UK registry | Companies House | Free, rate-limited; optional (without it, UK leads rely on incorporation markers on the site) |

Default prices live in `outbound/providers/pricing.py` and can be overridden with `PROVIDER_PRICES`; monthly caps per provider are set with `MONTHLY_CAPS_MICRO_USD`; the per-prospect ceiling is the workspace setting `budget_per_prospect_micro_usd`. The meter refuses a call before it would cross a cap and records the refusal.

**From Phase 6d:**
- Vendor keys, prices, caps, the finder chain and the model settings move from the environment into the database: `platform_credentials` is encrypted, and `platform_settings` holds the rest.
- Admins see and replace them in the console, and a change applies without a restart.
- Caps become per customer (the plan) and per platform (a tick job pauses a vendor at its cap).

**From 6g:** the verified lead directory is the free first link of the email waterfall, so a verified, fresh address replaces a finder lookup.

## 13. Delivery phases

| Phase | Scope | Gate |
|---|---|---|
| [0 Fix and bake-off](phases/phase-0-fix-and-bakeoff.md) | Stop duplicate drafts, repo hygiene, provider ports and adapters, vendor bake-off | A rerun makes no duplicate drafts; the waterfall chain is chosen from data |
| [1 Schema and persistence](phases/phase-1-schema-and-persistence.md) | 17 tables, migrations, repositories, state machines, policy seeds, legacy import | Migrations pass on SQLite and Postgres; the 10 xlsx rows are imported |
| [2 Engine on the CLI](phases/phase-2-engine-on-cli.md) | Providers, runner, all stages through drafting, Sent sync | 8 of 10 emails sent without edits; a rerun makes zero paid calls |
| [3 API and web app](phases/phase-3-api-and-web-app.md) | FastAPI, React app, intake webhook | Nothing reaches the mailbox without approval in the web app |
| [4 Close the loop](phases/phase-4-close-the-loop.md) | Follow-ups, reply triage, bounces, referrals, opt-outs, forget, reply webhook | A reply stops the sequence; a referral becomes a new contact |
| [5 Automated sending](phases/phase-5-automated-sending.md) | Gateway, send window, breaker, preflight | Switch turns on only after gates 2 and 4, warm-up, and legal sign-off |
| [6 SaaS alpha track](phases/phase-6-saas-ready.md) | Overview of 6a–6g | A second workspace runs with no data crossover, even with application scoping bypassed |
| [6a Tenancy foundation](phases/phase-6a-tenancy-foundation.md) | Composite FKs, row-level security, least-privilege roles, services per request, multi-tenant worker | Isolation holds with scoping patched out; the suite passes as `outbound_app` |
| [6b Identity and access](phases/phase-6b-identity-and-access.md) | Users, invitations, password reset, sessions, roles, superadmin, `/w/{slug}` | Every route tested against every role |
| [6c Onboarding and mailboxes](phases/phase-6c-onboarding-and-mailboxes.md) | IMAP, Graph and Gmail adapters, encrypted credentials, sender identity, onboarding | A customer drafts into its own M365 and IMAP mailbox from the browser |
| [6d Plans, limits and admin](phases/phase-6d-plans-limits-and-admin.md) | Per-step credits, grants, access time, resumable leads, vendor keys, admin console | Free plan 5+5 enforced and resumable; two pilot customers |
| 4a (from Phase 4) | Opt-out and hard-bounce handling, before the alpha | Opt-outs and bounces suppress and cancel |
| [6g Verified lead directory](phases/phase-6g-lead-directory.md) | Shared verified facts, first link of the waterfall, reports and reconfirmation | A verified fact saves another customer a paid lookup |
| [6e Billing](phases/phase-6e-billing.md), [6f Launch readiness](phases/phase-6f-launch-readiness.md) | After the alpha: payments; MFA, support role, CASA, directory legal steps, penetration test | Their checklists |
| [7 Later](phases/phase-7-later.md) | The backlog: everything deliberately left out, each with the need that would pull it in | None until an item is scheduled |

**Order:** 3b → 6a → 6b → 6c → 6d → 4a → **alpha** → 6g in parallel with the rest of 4 → after the alpha, 6e → 6f → 5. Phase 7 items are scheduled only on a measured need.

## 14. Testing and quality bar

How the code is tested, and where each rule below is proven, is in [technical/quality/testing-strategy.md](technical/quality/testing-strategy.md).

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
- **SaaS gates (Phase 6):**
  - an isolation suite calling every route with another workspace's ids;
  - the whole Postgres suite run as `outbound_app`, also with application scoping patched out;
  - a catalog test of every row-level-security policy and grant;
  - a role × route permission matrix, failing any route without `require`;
  - per-step charging and resume tests;
  - mailbox adapter contract tests (IMAP, Graph, Gmail);
  - privacy tests for the lead directory.

## 15. Risks

Known technical defects and gaps (not product risks) are tracked in [technical/tech-debt-and-risks.md](technical/tech-debt-and-risks.md).

| Risk | Mitigation |
|---|---|
| Vendor figures differ from the research | Bake-off first; every vendor sits behind one port |
| Many catch-alls stay unresolved | The resolver handles most; the held share is tracked from Phase 2 |
| Public LinkedIn search is still personal data | Legitimate-interests assessment, no scraping, a forget action |
| The Sent sync matches the wrong message | Match on recipient, subject and time window; an ambiguous match holds the follow-up |
| UK legal-entity detection misses a company | Companies House as a second source; operator can confirm by hand |
| A country rule is misread | Lawyer review before Phase 5; anything unknown is held |
| Scope creep | Deferred items stay deferred until a measured need appears |
| Supabase's Data API exposes the tables (found 2026-10-23) | **Closed:** migration 0009 revokes the `anon`/`authenticated` grants, and `outbound/db/isolation.py` refuses to start in production if they ever come back |
| Row-level security silently bypassed | The app never connects as the owner; a startup self-check; the suite runs as `outbound_app` |
| No MFA in the alpha, and the superadmin can read every workspace | Few platform accounts, long passwords, shorter staff sessions, audit of every view; MFA and the removal of superadmin come first after the alpha (6f) |
| Vendor keys stored in the database | Encrypted, with the key in Doppler; platform-only access; reveals audited; versions kept for rollback |
| Google restricted scopes need verification and CASA | The alpha fits the 100-user cap of an unverified app; IMAP fallback; apply during 6c |
| The lead directory's legal footprint and vendor terms (Hunter) | Accepted for the alpha; source kept per fact; a switch stops sharing; counsel before the public launch (6f) |
