---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Quality attributes

The [architecture's](architecture.md#1-introduction-and-goals) quality goals, broken into scenarios that can be checked. Each scenario names its stimulus, the required response, and what proves it today: a test, a check, or a gap in the [register](../tech-debt-and-risks.md). A scenario with no proof is a risk, not a feature.

Status key: **Proven** (a test or check runs in CI), **Partly** (proven in part; the gap is named), **Gap** (not proven or not true).

## 1. Safe and compliant

| ID | Scenario | Required response | Proof | Status |
|---|---|---|---|---|
| S1 | A lead's domain is added to the suppression list while it is mid-pipeline | The next guard moves it to `suppressed`; no stage runs for it again | `tests/db/test_runner.py::test_a_suppressed_domain_is_never_handed_to_a_stage` | Proven |
| S2 | A lead is approved, then its address is suppressed before deliver | Deliver holds it and withdraws the email; no draft is saved | `tests/db/test_review_and_deliver.py` | Proven |
| S3 | A target in a blocking country (DE) is imported | Disqualified at the gate, before any address is paid for | `tests/db/test_pipeline_e2e.py::test_a_german_target_is_disqualified_before_any_email_is_paid_for` | Proven |
| S4 | A UK sole trader is imported | Held for consent; nothing further is spent on it | `tests/db/test_pipeline_e2e.py::test_a_uk_sole_trader_is_held_and_nothing_further_is_spent_on_it` | Proven |
| S5 | A country rule is tightened after a lead was qualified | The next guard holds the lead; an approved email is withdrawn | `tests/db/test_runner.py::test_a_policy_that_now_needs_a_person_holds_the_lead_at_every_stage`, `…::test_holding_an_approved_lead_withdraws_its_approved_email` | Proven |
| S6 | Consent is recorded for the CEO, but the draft would go to the CTO | Email, copy and deliver refuse: only the recipient's consent counts | `tests/db/test_leads_and_settings.py` (recipient consent cases) | Proven |
| S7 | The operator skips a check (country rule, verification, person) and then approves | Approval is refused without an acknowledgement; with one, an `approved_with_skips` event is written | `tests/db/test_verification_skip.py`, `tests/db/test_policy_skip.py`, `web2/e2e/loop.spec.ts` | Proven |
| S8 | An email is never drafted without approval | Deliver only reads `approved` messages | `web2/e2e/loop.spec.ts` ("an unapproved email is never drafted") | Proven |
| S9 | An erasure request arrives for a person | Every personal field in every table is blanked, unsent messages are cancelled, drafts are deleted, and the address is suppressed | `tests/db/test_forget.py::test_forgetting_removes_every_trace_of_the_person`, `tests/db/test_privacy.py::test_forgetting_a_person_after_a_real_run_leaves_no_trace_anywhere` (each scans every text column) | Proven |
| S10 | A web page contains instructions aimed at the model | The text stays fenced as data | `outbound/prompts/fence.py` | **Gap**: the fence can be closed early ([R-08](../tech-debt-and-risks.md#r-08--p1--security-web-text-can-close-the-prompt-fence)); human approval remains the control |

## 2. Cost-controlled

| ID | Scenario | Required response | Proof | Status |
|---|---|---|---|---|
| C1 | The same pipeline is run twice over the same targets | The second run makes no paid vendor lookup; every repeated lookup is a `cache_hit` at cost 0. Model calls are not cached by design, so only a stage that runs again repeats them | `tests/db/test_pipeline_e2e.py::test_a_targets_list_becomes_drafts_and_a_rerun_costs_nothing` | Proven |
| C2 | A provider's monthly cap would be passed | The call is refused, recorded as `blocked_by_cap`, and `BudgetExceeded` is raised; a cached answer is still served | `tests/db/test_metered.py::test_a_call_that_would_pass_the_monthly_cap_is_refused_and_recorded`, `…::test_a_cached_answer_is_served_even_when_the_cap_is_reached` | Proven for finders, verifiers and search; **Gap** for resolver submits ([R-04](../tech-debt-and-risks.md#r-04--p1--cost-the-budget-cap-prices-a-catch-all-submit-at-0)) |
| C3 | A lead has used its per-prospect ceiling ($0.50 by default) | No more paid work; free stages still run | `tests/db/test_runner.py::test_a_lead_over_its_budget_gets_no_more_paid_work`, `…::test_a_free_stage_still_runs_for_a_lead_that_has_used_its_budget` | Partly: model spend is not counted ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)); a running worker does not see a changed ceiling ([R-10](../tech-debt-and-risks.md#r-10--p1--budget-a-running-worker-does-not-see-budget-changes-b4)) |
| C4 | Every vendor call is attributable | Each ledger row carries run, company and contact | `tests/db/test_pipeline_e2e.py::test_the_ledger_records_every_vendor_call_with_its_attribution` | Proven |
| C5 | Every path to a paid vendor, including intake's search, is metered | Same caps on every path | `tests/db/test_robustness.py::test_a_meter_applies_the_monthly_cap_to_every_path`, `…::test_the_search_used_by_intake_is_metered_with_the_same_caps` | Proven |
| C6 | Cost per prospect is reported | Spend per company and per vendor from the ledger | `GET /api/reports/cost`, `outbound report cost` | Partly: under-counts model spend ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)) |

## 3. Correct and recoverable

| ID | Scenario | Required response | Proof | Status |
|---|---|---|---|---|
| R1 | One lead's stage raises an error | That lead is `failed` with its stage and error; the run carries on | `tests/db/test_runner.py::test_a_failing_lead_is_marked_failed_and_the_run_carries_on` | Proven |
| R2 | The operator edits a lead while a stage is working on it | The operator's edit wins; the stage's result is dropped and the lead is tried again | `tests/db/test_runner.py::test_an_operator_edit_during_the_stage_wins_and_the_lead_is_tried_again` | Proven |
| R3 | The engine tries to overwrite a field the operator set | Not applied; recorded as an event | `tests/db/test_companies_repo.py::test_the_engine_cannot_overwrite_an_operator_value_but_the_attempt_is_recorded`, `tests/db/test_people_repo.py::test_the_engine_cannot_overwrite_an_operator_given_contact_field` | Proven |
| R4 | A draft is saved but the database write then fails | The draft is deleted again (undo) | `tests/db/test_runner.py::test_a_saved_draft_is_taken_back_when_the_database_write_cannot_happen` | Proven |
| R5 | A failed lead is retried | It waits 15 min × attempts; automatic retries stop after 3 | `tests/db/test_runner.py::test_the_wait_grows_with_each_failure_and_attempts_run_out` | Proven in code; **Gap** in production, because nothing runs `tick` ([R-02](../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7)) |
| R6 | The worker is killed mid-run | Leads lose nothing (C1 holds); the run is marked failed or recoverable | Leads: as C1. Run: **Gap**, it stays `running` ([R-05](../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3)) | Partly |
| R7 | A deploy fails after its migration ran | The previous release serves again | **Gap**: the rollback fails ([R-01](../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down)) | Gap |
| R8 | An illegal status change is attempted | Refused with `IllegalTransition`; nothing written | `tests/domain/test_state_machines.py`, `tests/db/test_runner.py::test_an_illegal_result_from_a_stage_fails_that_lead_not_the_run` | Proven (except runs: [R-15](../tech-debt-and-risks.md#r-15--p2--correctness-runs-and-three-tables-bypass-the-usual-guards)) |
| R9 | The same database runs on SQLite and Postgres | The whole suite passes on both | CI jobs `tests (SQLite)` and `tests (Postgres 16)` | Proven |
| R10 | The database is lost | Restore to a recent point | **Gap**: no backup procedure ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)) | Gap |

## 4. Operable by one person

| ID | Scenario | Required response | Proof | Status |
|---|---|---|---|---|
| O1 | A vendor key is missing | The worker and CLI say which key is missing and change nothing | `tests/test_cli.py::test_run_without_credentials_says_what_is_missing_and_changes_nothing` | Proven |
| O2 | The operator wants to know why a lead stopped | The lead page and journey show status, hold reason, the remedy, the event timeline and vendor calls | `web2/e2e/lead.spec.ts`, `web2/e2e/screens.spec.ts` | Proven |
| O3 | A deploy is made | One manual workflow; health-gated; logs on failure | `.github/workflows/deploy.yml`, `deploy/remote-deploy.sh` | Partly: the gate does not see the worker or the database ([R-06](../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database)) |
| O4 | An error happens in production | One JSON log line with an event name, request or run id, and no secrets or personal text | `tests/test_logging.py`, `tests/api/test_request_logging.py` | Partly: client IPs are logged ([R-14](../tech-debt-and-risks.md#r-14--p2--privacy-personal-data-in-logs)); there is no alerting |
| O5 | A new operator learns the app | A guided tour of every screen that cannot drift from the UI | `web2/e2e/tour.spec.ts` ("every step points at something that exists") | Proven |

## 5. Changeable

| ID | Scenario | Required response | Proof | Status |
|---|---|---|---|---|
| M1 | A new finder vendor is added | One adapter, one registry line, one price; no stage changes | The port and adapter structure; shared contract tests in `tests/contract/` | Proven by structure |
| M2 | Someone imports the database or a vendor client from the domain | CI fails | `uv run lint-imports` (3 contracts); ruff `banned-api` for `outbound.db.models` | Proven |
| M3 | A business rule changes | It is tested without a database | `tests/domain/` (529 cases, no I/O) | Proven |
| M4 | A test tries to reach the network | It fails | pytest `--disable-socket`; `tests/test_hygiene.py` | Proven |
| M5 | An API change leaves the web client stale | CI fails | The `web2` job regenerates the client and runs `git diff --exit-code` | Proven |

## How to refresh this page

```bash
# Every test named here still exists
grep -ohE "tests/[a-z_/]+\.py(::[a-z_]+)?" docs/technical/architecture/quality-attributes.md | sort -u |
while IFS= read -r ref; do
  f=${ref%%::*}; t=${ref#*::}
  test -e "$f" || echo "missing file $f"
  [ "$t" != "$ref" ] && ! grep -q "def $t" "$f" && echo "missing test $ref"
done
```

Then re-check each **Gap** and **Partly** against the register: when an entry closes, update the status here.
