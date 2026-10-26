---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Glossary

These are engineering terms as the code uses them. For the operator's vocabulary, see the [manual's glossary](../USER_MANUAL.md#15-glossary). Status names are listed in full in [state machines](hld/state-machines.md).

| Term | Meaning | Where in the code |
|---|---|---|
| **Acknowledge skips** | At approval, the operator's explicit confirmation that an email relies on a skipped check. Recorded as an `approved_with_skips` event. Without it, approval is refused | `outbound/services/review.py::ReviewService.approve` |
| **Adapter** | The one class that talks to one vendor and maps its JSON into a port's model. Vendor JSON never leaves it | `outbound/providers/adapters/` |
| **Anchor** | What an intake row is identified by: a domain, a company name, an email, a person and company, or a LinkedIn URL | `outbound/domain/enums.py::ImportAnchor` |
| **Catch-all** | A mail domain that accepts every address, so a verifier cannot tell whether a mailbox exists. A **resolver** is a second vendor that tries to decide | `EmailStatus.CATCH_ALL_*` |
| **Call scope** | The run, company and contact a paid call is charged to, carried in a context variable | `outbound/metering/metered.py::call_scope` |
| **Container** | The composition root: settings, database engine and unit-of-work factory, built once per process | `outbound/bootstrap.py::Container` |
| **Country policy** | The per-country rule for cold email (`allow`, `allow_with_footer`, `consent_required`, `block`), plus extra conditions such as "corporate subscribers only" or allowed address sources | `outbound/domain/policies.py::decide_country_policy` |
| **Defer** | Postpone a lead by moving `next_action_at` forward, without changing its status. Used where the lifecycle allows no hold or failure | `outbound/runner/runner.py::Runner._defer` |
| **Event** | An append-only row in `events` recording a status change, a field change, or an operator action, with the actor | `outbound/db/repositories/base.py::EventRepository` |
| **Fence** | Wrapping untrusted text (web pages, vendor data) in `<untrusted>` tags, so the model treats it as data. See [R-08](tech-debt-and-risks.md#r-08--p1--security-web-text-can-close-the-prompt-fence) | `outbound/prompts/fence.py` |
| **Fit gate** | The campaign's minimum fit score. Operator-chosen leads bypass it, but their score is still recorded | `outbound/domain/policies.py::passes_fit_gate` |
| **Guard** | A check the runner makes before calling a stage: suppression, country policy, per-prospect budget | `outbound/runner/guards.py::Guards` |
| **Hold** | A lead in `held` with a `hold_reason`, waiting for a person or an outside answer. The reason decides where it resumes | `outbound/domain/state_machines.py::resume_status_for` |
| **Lead** | A row in `companies`. The company is the unit of work: one lead, one first email | `outbound/db/models.py` |
| **Ledger** | The `provider_calls` table: one row per paid call, cache hit or refusal, each committed in its own transaction | `outbound/metering/metered.py::Meter` |
| **Manual fields** | The fields an operator has set on a row. The engine never overwrites them; it records its own value as an event instead | `outbound/db/repositories/base.py::ScopedRepository._apply_changes` |
| **Meter** | The decorator every paid call passes through: cache, then budget check, then the call, then a ledger row | `outbound/metering/metered.py` |
| **Micro-USD** | Money as an integer number of millionths of a dollar. $0.50 is `500_000` | `outbound/domain/money.py` |
| **Operator** | The one human user. The actor string is `operator` | `outbound/domain/actors.py` |
| **Policy skip** | An operator's decision that the country rule does not apply to one lead from a given stage onward (`companies.policy_skip_from`). The skip covers that stage and every later stage, never an arbitrary set of stages | `outbound/domain/policies.py::policy_skipped_at` |
| **Port** | A `Protocol` describing what the engine needs from a kind of vendor (finder, verifier, resolver, search, LLM, registry, mailbox) | `outbound/providers/ports.py` |
| **Provenance** | How an address was obtained: `operator_given`, `publicly_published`, `api_database`, `pattern_inferred`, `referral`. Some countries allow only some provenances | `outbound/domain/enums.py::Provenance` |
| **Recipient consent** | Consent counts only for the person it was recorded for. Before a recipient is chosen, anyone's consent at the company keeps the lead moving | `outbound/stages/policy.py::policy_decision_for` |
| **Row version** | An optimistic-locking counter on `companies` and `messages`. Every update checks it, and a stale write raises `ConcurrencyConflict` | `outbound/db/models.py`, `outbound/db/uow.py` |
| **Run** | A row in `runs`: one execution of the pipeline (or a sync), queued by the API or started by the CLI, with its counts and cost | `outbound/db/repositories/audit.py::RunRepository` |
| **Runner** | The plain-Python loop that picks due leads per stage, guards them, calls the stage, and writes the result | `outbound/runner/runner.py::Runner` |
| **Safe to send** | The rule that an address may be drafted to: a good verification status (or a skipped check), no suppression, the country allows it, and the contact is workable | `outbound/domain/policies.py::check_send` |
| **Stage** | One step of the pipeline with an input status. It does its network work with no transaction open and returns a `StageResult` | `outbound/stages/base.py::Stage` |
| **StageResult** | What a stage returns: the next status, fields to update, child rows to write, and an optional undo | `outbound/stages/base.py::StageResult` |
| **Suppression** | A hashed email or domain that must never be contacted. It always wins over every other rule and every skip | `outbound/db/repositories/suppressions.py` |
| **Tick** | One scheduled pass: retry due failures, run the catch-all poller and the Sent sync, then run the pipeline. See [R-02](tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7) | `outbound/runner/tick.py::Tick` |
| **Touch** | One email in a sequence: `step` 0 is the first email, 1 and 2 are follow-ups (Phase 4) | `messages.step` |
| **Unconfirmed contact** | A person a search only mentions alongside the company. They are not worked on until the operator confirms they work there | `ContactStatus.UNCONFIRMED` |
| **Unit of work** | One database session and transaction, with every repository bound to it. Nothing is written unless `commit()` is called | `outbound/db/uow.py::UnitOfWork` |
| **Verification skipped** | The operator's decision to treat one address as sendable without proof (`contact_emails.verification_skipped`). Suppression still applies, and approval needs an acknowledgement | `outbound/domain/policies.py::is_sendable` |
| **Waterfall** | The ordered search for a contact's address: addresses already held, then one published on the site, then the learned pattern, then each paid finder, verifying each result | `outbound/stages/email/waterfall.py` |
| **Worker** | The process that claims queued runs from `runs` and executes them | `outbound/worker.py::Worker` |
| **Workspace** | The tenant. Every query is scoped by `workspace_id`. There is one workspace until Phase 6 | `outbound/db/models.py` |
