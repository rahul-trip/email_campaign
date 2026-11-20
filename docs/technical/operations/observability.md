---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-19 (25cc02f)
applies_to: Phase 6
---

# Observability

How to see what Outbound is doing and why. There are three sources:

- **Logs:** what the processes did. Ephemeral; on the VM.
- **The `events` table:** what happened to each record, and who did it. Durable; in the database.
- **The `provider_calls` ledger:** every paid call, its cost and its answer. Durable.

There are no metrics, traces or alerts yet. The [SLOs](slos.md) say what to watch and how to measure it with what exists today.

## Logs

**Format.** One JSON object per line on stderr (`LOG_FORMAT=json` in production; `auto` prints JSON unless stderr is a terminal: `outbound/logging.py::configure_logging`), collected by Docker's json-file driver: 10 MB × 5 files per container. Every line has:

- `timestamp` (UTC);
- `level`;
- `logger`;
- `event`;
- `service` (`outbound`);
- `version` (the package version, which does not identify the release: [R-19](../tech-debt-and-risks.md#r-19--p3--housekeeping-stale-references-and-inconsistent-versions));
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

The events that matter when you watch the system, grouped by area. Fields that come from bound context (`run_id`, `workspace_id`, `company_id`, ...) are not repeated. To list every event, use "How to refresh this page". Never a person's name or address: lines carry ids.

**Processes and requests**

| Event | Level | Module | Fields | Means |
|---|---|---|---|---|
| `service_started` | INFO | `cli/serve.py` | api: `role`, `host`, `port`, `database` (password hidden), `log_level`. worker: `role`, `threads`, `lead_concurrency`, `pool_size`, `tick_minutes`, `check_minutes`, `poll_seconds`, `database` | A process is up |
| `tenant_isolation_unsafe` | ERROR | `cli/serve.py` | `problem`, `refused` | The database role could bypass row-level security; the process refuses to start |
| `http_request` | DEBUG (health, status and asset paths when under 400) / INFO / WARNING (4xx) / ERROR (5xx) | `api/request_log.py` | `method`, `path` (route template), `status`, `duration_ms` | One HTTP request |
| `unhandled_error` | ERROR + traceback | `api/errors.py` | `error_type`, `method`, `path`, `request_id` | A bug; the user saw a 500 with this `request_id` |
| `workspace_refused`, `superadmin_view` | WARNING | `api/deps.py` | `workspace_id` | A request named a workspace the person may not use; a superadmin read a workspace |
| `vendors_unreadable` | WARNING | `api/app.py` | `error_type` | Vendor keys could not be read from the database at start |
| `login_succeeded` | INFO | `services/identity.py` | `user_id` | A person signed in |
| `login_failed` | WARNING | `services/identity.py` | `user_id` (null for an unknown address) | Wrong password |

The login throttle (5 failures in 60 s from one address) answers 429 and logs no line of its own: see [runbook: login throttle](runbooks/login-throttle-or-cookie.md).

**Worker**

| Event | Level | Fields | Means |
|---|---|---|---|
| `worker_status` | INFO | `threads`, `busy`, `queued`, `oldest_queued_seconds`, `overdue_ticks` | Once a minute (`STATUS_EVERY`, 60 s): the same numbers the worker writes as its heartbeat |
| `run_claimed` | INFO | `run_id`, `workspace_id`, `params` | The worker took a queued run |
| `run_stale_failed` | WARNING | `run_id`, `stale_minutes` | A running run with no heartbeat was failed |
| `run_failed`, `pipeline_failed`, `tick_failed`, `auto_discovery_failed`, `notify_failed`, `periodic_failed` | ERROR + traceback | `error_type` (and `run_id` or `workspace_id`) | That piece of work raised; the worker goes on with the others |
| `tick_skipped`, `pipeline_skipped` | INFO | `workspace_id`, `reason` | A run is in progress, so the pass waits |
| `worker_error` | ERROR + traceback | `error_type` | The worker loop hit an error (often the database); it keeps polling |
| `job_failed` | ERROR + traceback | `job` (`runner/tick.py`) | A tick job (poller, Sent sync, inbox sync) failed |

**Runner and stages**

| Event | Level | Fields | Means |
|---|---|---|---|
| `run_started` | INFO | `stages`, `limit_per_stage` | A pipeline run began |
| `run_finished` | INFO / ERROR | `status`, `duration_ms`, `cost_micro_usd`, `outcomes` (per stage) | A run ended |
| `stage_done` | INFO | `stage`, `company_id`, `to_status`, `reason` | A lead moved |
| `guard_refused` | INFO | `stage`, `company_id`, `kind` (suppressed, hold, budget), `reason`, `outcome` | A guard stopped a lead before a stage |
| `stage_failed` | ERROR + traceback | `error` | A stage raised; the lead is failed or deferred |
| `lead_gone_during_run`, `lead_unreadable`, `undo_failed` | INFO / ERROR | `stage`, `company_id` | A lead was deleted mid-run; could not be loaded; an outside effect (a draft) could not be taken back |
| `catch_all_poll_failed` | ERROR + traceback | `company_id` | Polling one lead failed |
| `vendor_failed_trying_next`, `realtime_resolver_failed` | WARNING | `role`, `vendor`, `error`, `status_code` | An email vendor failed; the waterfall goes on |
| `mailbox_unavailable`, `mailbox_not_opened`, `mailbox_check_failed`, `sent_sync_mailbox_failed`, `inbox_sync_mailbox_failed` | WARNING | `mailbox_id`, `status` or `reason` | A workspace mailbox could not be used |
| `sent_sync_ambiguous` | WARNING | `message_id`, `candidates` | A draft matched several sent mails |
| `employment_check_failed`, `news_search_failed`, `team_pages_unread`, `linkedin_draft_failed` | WARNING | `reason` | A research or contact step could not finish; the lead goes on |

**Vendors and metering**

| Event | Level | Fields | Means |
|---|---|---|---|
| `provider_call` | DEBUG (cache hit) / INFO / WARNING (error) | `provider`, `operation`, `outcome`, `cost_micro_usd`, `latency_ms` | One vendor call |
| `provider_call_blocked` | WARNING | `provider`, `operation`, `outcome`, `reason` | A spend cap refused a call |
| `provider_retry` | WARNING | `provider`, `request`, `attempt`, `max_attempts`, `wait_seconds`, `reason`, `status_code` | A retryable vendor error; retrying |
| `vendor_key_skipped` | WARNING | `vendor`, `key`, `error`, `status_code` | A key was refused; the next key is tried |
| `vendor_balance_unreadable` | WARNING | `vendor`, `error_type` | A vendor's balance could not be read |
| `vendors_credit_handled`, `vendors_paused_by_cap` | WARNING | `paused`, `resumed` / `vendors` | Vendors paused or resumed for credit or a cap |
| `vendor_key_replaced`, `vendor_key_removed`, `vendors_reloaded` | INFO | `vendor`, `version`, `slot` | Staff changed vendor keys |
| `credits_resumed` | INFO | `leads`, `rows` | Leads that waited for AI credits resumed |

**Discovery, mailboxes, privacy and notices**

| Event | Level | Fields | Means |
|---|---|---|---|
| `discovery_done` | INFO | `asked`, `calls`, `found`, `added`, `rejected`, `unscreened` | A discovery run ended |
| `discovery_*_failed`, `discovery_page_unread` | WARNING | `source`, `reason` | One source, search or screening step failed; the run goes on |
| `auto_discovery_queued`, `auto_discovery_skipped` | INFO / DEBUG | `run_id`, `campaign` / `reason` | The automatic discovery run was queued or skipped |
| `auto_approved`, `auto_approve_left` | INFO / WARNING | `message_id` | A cold draft was approved without a person, or could not be |
| `inbound_handled` | INFO | `category`, `acted` | A reply or bounce was classified |
| `mailbox_connected`, `mailbox_disconnected`, `oauth_connect_failed`, `oauth_revoke_failed` | INFO / WARNING | `mailbox_id`, `gateway`, `reason` | Mailbox connection changes |
| `intake_search_failed` | WARNING | `error_type`, `reason` | A name lookup failed; the row waits |
| `draft_delete_failed` | WARNING | `remote_draft_id`, `reason` | A draft could not be deleted from the mailbox |
| `lead_deleted` | WARNING | `company_id`, `domain`, `status_was`, counts, `drafts_left`, `domain_suppressed` | A lead was deleted for good |
| `customer_deleted`, `customer_delete_failed`, `account_deleted` | INFO / ERROR | `workspace_id`, `rows`, `user_id` | A workspace or account was removed |
| `notices_sent`, `notice_failed`, `staff_alert_failed`, `email_failed`, `email_not_sent` | INFO / WARNING | `subject`, `reason` | A notice or transactional email went out or did not |


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
- `cost_micro_usd` (what the platform paid), `credits_milli` (what the customer is charged, in thousandths of an AI credit), `latency_ms`;
- `detail` (what the call asked and got);
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

Model calls are recorded at $0 unless `LLM_PRICES` is set; AI credits are metered per call regardless ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5--ai-credits-fixed-2026-11-18-dollars-still-open)).

## Built-in reports

| Report | Where | Shows |
|---|---|---|
| Status | Dashboard; `GET /api/status`; `outbound status` | Leads by status, holds by reason, failures, the review queue |
| Quality | Reports; `outbound report quality` | Unedited share of sent first emails (target 80 %), flag rate, holds, catch-all share |
| Funnel | Reports; `outbound report funnel --days N` | Companies named and how many the model read, what became of them, where the leads added are now, vendor failure rates: the baseline for lead-quality changes |
| Cost | Reports; `outbound report cost --days N` | Spend by vendor and per prospect, paid calls |
| Runs | Runs screen; `GET /api/runs` | Status, counts per stage and outcome, cost |
| Lead journey | Lead page → Journey | One lead's eight stages, incidents and vendor calls |
| Worker | Admin console → Overview → Worker card; `GET /api/admin/overview` | Last report, workspaces being worked on (`busy` of `threads`), runs waiting and the oldest wait, late 15-minute passes. "Not responding" when there is no report for three minutes |

### Where a lead's time goes

`scripts/lead_timings.py` is a read-only report of the call ledger and the status history, for every workspace. Run it before a change to the worker or the stages and again after, to see what the change gained.

```bash
uv run python -m scripts.lead_timings                 # the last 7 days, every workspace
uv run python -m scripts.lead_timings --days 2
uv run python -m scripts.lead_timings --workspace default
```

It prints three things:

1. the 15 vendor and model operations that take the most time in all (calls, median, 95th percentile, total), from `provider_calls.latency_ms`;
2. how long leads wait before each status (the gap since the lead's previous change, so it includes waiting for a run), median and 95th percentile, from the company status changes in `events`;
3. the first-draft time: from a lead's first change to `copy_ready` (the email waiting for review).

It reads through `container.uow(workspace_id)` for each workspace, so it needs the same database settings as the app.

The worker writes the same numbers to its own row in the platform settings (`PlatformSettingsRepository.beat_worker`) on each `worker_status` pass, which is what the Worker card reads. See [runbook: work is not picked up](runbooks/work-not-picked-up.md).

## What to watch

There is no alerting. Until there is, the operator or engineer should check these daily (the [SLOs](slos.md) give targets):

| Signal | How |
|---|---|
| Any `"level": "error"` in `api` or `worker` | `oc logs --since 24h <svc> \| grep '"level": "error"'` |
| The worker is up and not crash-looping | The admin Worker card; `oc ps` (restart count); a `worker_status` line each minute |
| No run stuck in `running` | The Runs screen ([R-05](../tech-debt-and-risks.md#r-05--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3--closed-2026-10-23)) |
| Spend against budget | Reports → cost; `provider_call_blocked` lines |
| Vendor trouble | `provider_retry` and `provider_call` with `outcome: error` |
| Leads stuck | Failed leads page: held and failed |
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
