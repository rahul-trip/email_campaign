---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# The worker keeps restarting

| | |
|---|---|
| **Severity** | SEV-2 |
| **Impact** | Queued runs are never executed. The web app shows a run "queued" for more than 45 s ("worker stuck"). |
| **Signals** | `oc ps` shows `worker` restarting; its logs repeat `not configured: …`; a deploy still succeeded (R-06) |
| **Related** | [R-06](../../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database), [configuration reference](../configuration-reference.md) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc ps -a
oc logs --tail 30 worker
```

- `not configured: <provider>: …` means a key named in `FINDER_CHAIN`, `VERIFIER` or `CATCH_ALL_RESOLVER`, or `TAVILY_API_KEY`, or the LLM key, is missing in Doppler.
- A traceback at start means a configuration error (for example `POSTGRES_URL`) or a bug.

## 2. Contain

Nothing to contain: no work is done while it loops.

## 3. Fix

- Add the missing key to Doppler `prd`, or remove that provider from the chain, then restart: `oc up -d --force-recreate worker`.
- For a bug, roll forward with a fix.

## 4. Verify

The worker logs `service_started` (`role: worker`) and stays up; a queued run moves to `running`.

## 5. Follow up

Check the deploy's post-checks, which would have caught this ([release and rollback](../release-and-rollback.md#checking-a-release)).
