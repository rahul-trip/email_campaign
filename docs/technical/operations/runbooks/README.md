---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Runbooks

One page per symptom. Each page follows the same order: **confirm** (read-only first), **contain**, **fix**, **verify**, **follow up**. For severity and the first 15 minutes, see [incident response](../incident-response.md). For a new failure mode, add a page from the [template](../../_templates/runbook.md) in the same pull request that adds the failure.

Commands assume the VM, the deploy user, and the `oc` alias:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

SQL assumes the Supabase SQL editor, or `psql` through Doppler. Always filter by `workspace_id` (`:ws`). Look it up with `SELECT id FROM workspaces WHERE name = 'default';`.

| You see | Runbook | Severity |
|---|---|---|
| The deploy workflow fails; the step summary shows `deploy of <sha> failed`; `the rollback is not healthy either`; `oc ps -a` shows `migrate` exited non-zero | [A deploy failed, or the rollback left the site down](deploy-failed-or-rollback.md) | SEV-2 |
| `doppler.env is missing` (deploy preflight); `Doppler Error: … token` in container logs; containers exiting at start | [Doppler token rejected, or Doppler unreachable](doppler-token-or-outage.md) | SEV-2 |
| `password authentication failed`; `Network is unreachable`; `could not translate host name`; `worker_error` lines; 500s with `unhandled_error` | [The database refuses the login, or cannot be reached](db-auth-or-unreachable.md) | SEV-2 |
| `max clients reached` or `remaining connection slots are reserved` in the logs | [The database says too many clients](db-max-clients.md) | SEV-2 |
| `oc ps` shows `worker` restarting; its logs repeat `not configured: …`; a deploy still succeeded (R-06) | [The worker keeps restarting](worker-crash-loop.md) | SEV-2 |
| A run in `running` with no recent `stage_done` lines; it started before a deploy or a worker restart | [A run stays "running" for ever](run-stuck-running.md) | SEV-3 |
| `provider_call_blocked` (WARNING); leads `failed` with "per-prospect budget used up"; Tavily `BudgetExceeded` (plan limit); the cost report | [Paid calls are being refused, or spend is higher than expected](budget-exceeded.md) | SEV-2 |
| `provider_retry` WARNINGs; `provider_call` with `outcome: error`; leads `failed` with a provider name in `last_error`; `ProviderAuthError` (401/403) | [A vendor is failing or rate-limiting](vendor-429-or-outage.md) | SEV-3 |
| Leads stuck in `approved` with `deferred` events; `job_failed` for `SentSync`; IMAP errors (`LOGIN failed`, timeouts, `APPEND … failed`) | [Drafts are not saved, or the Sent sync fails](imap-failure.md) | SEV-3 |
| Needs attention screen; `outbound status` shows many catch-all holds | [Leads pile up held as catch-all](catch-all-backlog.md) | SEV-3 |
| Needs attention screen; the lead page shows the reason and the fix; **Release** is refused with "Nothing has changed since it was held" | [Leads are held by a country rule](leads-held-by-policy.md) | SEV-3 |
| A reply or message asking to be removed, to stop, or for a copy of their data | [Someone asks to be erased, or asks what is held about them](erasure-request.md) | SEV-2 |
| gitleaks failed in CI or pre-commit; a secret seen in a log, a paste, a screenshot or a commit; unexpected vendor spend; unknown logins | [A secret has leaked](secret-leaked.md) | SEV-1 |
| `429 too_many_attempts`; sign-in appears to succeed but the next page asks again (cookie not kept); `login_throttled` for every client at once | [The operator cannot sign in](login-throttle-or-cookie.md) | SEV-3 |
| `migrate` exited non-zero with an Alembic or database error (not `Can't locate revision`, which is [R-01](deploy-failed-or-rollback.md)) | [A migration failed during a deploy](migration-failed.md) | SEV-2 |
| Leads in `failed` with a past `next_action_at`; `held` catch-all leads never released; no `sync` runs in the Runs list | [Scheduled work is not happening](tick-not-running.md) | SEV-3 |
