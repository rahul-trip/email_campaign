---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Observability

How to see what Outbound is doing and why. There are three sources:

- **Logs:** what the processes did. Ephemeral; on the VM.
- **The `events` table:** what happened to each record, and who did it. Durable; in the database.
- **The `provider_calls` ledger:** every paid call, its cost and its answer. Durable.

There are no metrics, traces or alerts yet. The [SLOs](slos.md) say what to watch and how to measure it with what exists today.

## Logs

**Format.** One JSON object per line on stderr (`LOG_FORMAT=json` in production), collected by Docker's json-file driver: 10 MB × 5 files per container. Every line has:

- `timestamp` (UTC);
- `level`;
- `logger`;
- `event`;
- `service` (`outbound`);
- `version` (the package version, `0.0.1`, which does not identify the release: [R-19](../tech-debt-and-risks.md#r-19--p3--housekeeping-stale-references-and-inconsistent-versions));
- `environment`;
- the bound context: `request_id`, `client_ip`, `run_id`, `workspace_id`, `company_id`, `stage`.

Redaction is described in [logging](../lld/logging.md).

**Reading them on the VM:**

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
oc logs -f worker                                             # follow
oc logs --since 1h api | grep '"level": "error"'              # errors in the last hour
oc logs --since 24h worker | grep '"event": "run_finished"'   # runs, with outcomes and cost
oc logs --since 24h worker | grep '"run_id": "<id>"'          # everything about one run
oc logs --since 1h api | grep '"request_id": "<ref>"'         # the reference a user saw on a 500
```

### Log event catalogue

All 27 events. Fields that come from bound context (`run_id`, `company_id`, …) are not repeated.

| Event | Level | Module | Fields | Means |
|---|---|---|---|---|
| `service_started` | INFO | `cli/serve.py` | `role` (api or worker), `workspace_id`, `host`, `port`, `poll_seconds`, `log_level`, `database` (password hidden) | A process is up |
| `http_request` | DEBUG (quiet paths) / INFO / WARNING (4xx) / ERROR (5xx) | `api/request_log.py` | `method`, `path` (route template), `status`, `duration_ms` | One HTTP request |
| `unhandled_error` | ERROR + traceback | `api/errors.py` | `error_type`, `method`, `path`, `request_id` | A bug; the user saw a 500 with this `request_id` |
| `login_succeeded` | INFO | `api/routers/auth.py` | `client_ip`, `session_hours` (shown redacted) | Operator signed in |
| `login_failed` | WARNING | `api/routers/auth.py` | `client_ip` | Wrong password |
| `login_throttled` | WARNING | `api/routers/auth.py` | `client_ip` | 5 failures in 60 s from that address |
| `run_claimed` | INFO | `worker.py` | `run_id`, `params` | The worker took a queued run |
| `run_started` | INFO | `runner/runner.py` | `stages`, `limit_per_stage` | A pipeline run began |
| `run_finished` | INFO / ERROR | `runner/runner.py` | `status`, `duration_ms`, `cost_micro_usd`, `outcomes` (per stage) | A run ended |
| `run_failed` | ERROR + traceback | `worker.py` | `run_id`, `error_type` | A run failed outright |
| `worker_error` | ERROR + traceback | `worker.py` | `error_type` | The worker loop hit an error (often the database); it keeps polling |
| `stage_done` | INFO | `runner/runner.py` | `stage`, `company_id`, `to_status`, `reason` | A lead moved |
| `guard_refused` | INFO | `runner/runner.py` | `stage`, `kind` (suppressed, hold, budget), `reason`, `outcome` | A guard stopped a lead before a stage |
| `stage_failed` | ERROR + traceback | `runner/runner.py` | `error` | A stage raised; the lead is failed or deferred |
| `lead_gone_during_run` | INFO | `runner/runner.py` | `stage`, `company_id` | The operator deleted a lead mid-run |
| `lead_unreadable` | ERROR + traceback | `runner/runner.py` | `stage`, `company_id` | A lead could not be loaded |
| `undo_failed` | ERROR + traceback | `runner/runner.py` | — | An outside effect (a draft) could not be taken back |
| `job_failed` | ERROR + traceback | `runner/tick.py` | `job` | A tick job (poller, Sent sync) failed |
| `catch_all_poll_failed` | ERROR + traceback | `stages/email/poller.py` | `company_id` | Polling one lead failed |
| `sent_sync_ambiguous` | WARNING | `stages/sync.py` | `message_id`, `candidates` | A draft matched several sent mails |
| `provider_call` | DEBUG (cache hit) / INFO / WARNING (error) | `metering/metered.py` | `provider`, `operation`, `outcome`, `cost_micro_usd`, `latency_ms` | One vendor call |
| `provider_call_blocked` | WARNING | `metering/metered.py` | `provider`, `operation`, `outcome`, `reason` | A spend cap refused a call |
| `provider_retry` | WARNING | `providers/http.py` | `provider`, `request`, `attempt`, `max_attempts`, `wait_seconds`, `reason`, `status_code` | A retryable vendor error; retrying |
| `intake_search_failed` | WARNING | `services/intake.py` | `error_type`, `reason` | A name lookup failed; the row waits |
| `privacy_action` | INFO / WARNING (drafts left) | `services/privacy.py` | `action`, `actor`, `found`, `messages_cancelled`, `drafts_deleted`, `drafts_left` | Forget or suppress done |
| `draft_delete_failed` | WARNING | `services/privacy.py` | `remote_draft_id`, `reason` | A draft could not be deleted from the mailbox |
| `lead_deleted` | WARNING | `services/privacy.py` | `company_id`, `domain`, `status_was`, counts, `domain_suppressed` | A lead was deleted for good |

## The events table

Every status change and operator action writes an `events` row (`entity_type`, `entity_id`, `type`, `actor`, `data`, `created_at`), in the same transaction as the change. This is the audit trail. The lead page's timeline and the journey are built from it.

| Type | Written by | `data` |
|---|---|---|
| `created` | company, contact and message repositories | — |
| `status_changed` | company, contact, contact-email and message transitions | `from`, `to`, `reason`, `hold_reason`, `failed_stage`, `error` |
| `field_changed` | `ScopedRepository._apply_changes` | `field`, `old`, `new`, `source`, `applied` |
| `deferred` | `Runner._defer` (once per distinct reason) | `reason` |
| `intake_accepted`, `intake_merged` | `services/intake.py` | `source`; the conflicting values on a merge |
| `consent_recorded`, `consent_withdrawn` | `db/repositories/contacts.py` | basis |
| `email_verification_skipped`, `email_verification_restored` | `ContactEmailRepository.set_verification_skipped` | `status`, `reason` |
| `policy_skip_granted`, `policy_skip_revoked` | `services/leads.py` | `from_stage`, `reason` |
| `edited`, `approved_with_skips`, `rejected` | `services/review.py` | `edit_distance`; skip kinds; reason |
| `sync_ambiguous` | `stages/sync.py` | candidate Message-IDs |
| `suppression_added` | `db/repositories/suppressions.py` | kind, reason (never the value) |
| `forgotten` | `services/forget.py` | no personal data |
| `lead_deleted`, `person_removed` | `db/repositories/erasure.py` | domain and counts; contact id |
| `policy_changed`, `policy_deleted` | `services/settings.py` | country, rule, version |
| `settings_changed`, `sender_profile_reviewed` | `services/settings.py` | changed settings; changed field names |
| `legacy_imported` | `services/legacy_import.py` | — |

Useful queries. Always filter by `workspace_id`:

```sql
-- One lead's story
SELECT created_at, type, actor, data FROM events
WHERE workspace_id = :ws AND entity_type = 'company' AND entity_id = :company_id ORDER BY created_at;

-- What the operator skipped or acknowledged in the last week
SELECT created_at, entity_id, type, data FROM events
WHERE workspace_id = :ws AND type IN ('policy_skip_granted','email_verification_skipped','approved_with_skips')
  AND created_at > now() - interval '7 days';
```

## The provider-call ledger

One `provider_calls` row per paid call, cache hit, error or cap refusal, with:

- `provider`, `operation`, `outcome` (`hit`, `miss`, `error`, `cache_hit`, `blocked_by_cap`);
- `cost_micro_usd`, `latency_ms`;
- `run_id`, `company_id`, `contact_id`;
- `request_hash`, and `response` (the vendor's answer).

It feeds the cost report, the run's cost, the lead page's vendor-call view, and the per-prospect ceiling. See [metering](../lld/metering.md).

```sql
-- Spend by provider this month
SELECT provider, count(*), sum(cost_micro_usd)/1e6 AS usd FROM provider_calls
WHERE workspace_id = :ws AND created_at >= date_trunc('month', now()) GROUP BY provider;

-- Error rate by provider, last 24 h
SELECT provider, avg((outcome = 'error')::int) AS error_rate, count(*) FROM provider_calls
WHERE workspace_id = :ws AND created_at > now() - interval '1 day' GROUP BY provider;
```

Model calls are recorded at $0 unless `LLM_PRICES` is set ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)).

## Built-in reports

| Report | Where | Shows |
|---|---|---|
| Status | Dashboard; `GET /api/status`; `outbound status` | Leads by status, holds by reason, failures, the review queue |
| Quality | Reports; `outbound report quality` | Unedited share of sent first emails (target 80 %), flag rate, holds, catch-all share |
| Cost | Reports; `outbound report cost --days N` | Spend by vendor and per prospect, paid calls |
| Runs | Runs screen; `GET /api/runs` | Status, counts per stage and outcome, cost |
| Lead journey | Lead page → Journey | One lead's eight stages, incidents and vendor calls |

## What to watch

There is no alerting. Until there is, the operator or engineer should check these daily (the [SLOs](slos.md) give targets):

| Signal | How |
|---|---|
| Any `"level": "error"` in `api` or `worker` | `oc logs --since 24h <svc> \| grep '"level": "error"'` |
| The worker is up and not crash-looping | `oc ps` (restart count); no `not configured` in its logs |
| No run stuck in `running` | The Runs screen ([R-05](../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3)) |
| Spend against budget | Reports → cost; `provider_call_blocked` lines |
| Vendor trouble | `provider_retry` and `provider_call` with `outcome: error` |
| Leads stuck | Needs attention screen: held and failed |
| Ambiguous Sent matches | `sent_sync_ambiguous` |

## Gaps

No metrics endpoint; no tracing; no error tracker; no log shipping (logs live on the VM for days); no alerting; health checks that do not see the worker or the database ([R-06](../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database)). These are recorded, not planned. In proportion to one operator and a batch workload, the cheapest next steps are:

- a deep health check;
- a cron job that greps the last day's logs for errors and mails them.

## How to refresh this page

```bash
# every log event, with level and module
uv run python - <<'EOF'
import ast, pathlib
for p in pathlib.Path("outbound").rglob("*.py"):
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("debug","info","warning","error","exception") \
           and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            print(n.args[0].value, n.func.attr, p)
EOF
# every events-table type
grep -rn "events.append\|_record_change(" outbound
```
