---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# A deploy failed, or the rollback left the site down

| | |
|---|---|
| **Severity** | SEV-2 (SEV-1 if the site stays down during a live campaign) |
| **Impact** | The web app may be down; no runs execute. Data is safe in Supabase. |
| **Signals** | The deploy workflow fails; the step summary shows `deploy of <sha> failed`; `the rollback is not healthy either`; `oc ps -a` shows `migrate` exited non-zero |
| **Related** | [R-01](../../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down), [release and rollback](../release-and-rollback.md) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc ps -a                                   # which containers run; migrate's exit code
oc logs --tail 100 migrate                 # "Can't locate revision identified by '…'" = R-01
oc logs --tail 100 api worker
readlink /opt/outbound/current             # which release is current now
ls -1t /opt/outbound/releases | head
```

| What you see | Meaning |
|---|---|
| The build failed (workflow log) | Nothing changed; the old release is still running. Fix the build and deploy again |
| `migrate` failed with `Can't locate revision` after a rollback | R-01: the old code's `migrate` refuses the newer database. The site is down |
| `migrate` failed with an auth or network error | See [database auth or unreachable](db-auth-or-unreachable.md) |
| `api` up but `/api/health` failing | Read the `api` logs: usually configuration (`OPERATOR_PASSWORD_HASH`, `SESSION_SECRET`) |

## 2. Contain

- If the new release is healthy enough to serve but has a bug, **roll forward**: fix it and deploy a new commit. This is the preferred path after any migration.
- If the site is down because of R-01, bring the previous release's `api` and `worker` up **without** `migrate`, as in [release and rollback: rolling back](../release-and-rollback.md#rolling-back):

```bash
cd /opt/outbound
PREV=<previous sha>
export OUTBOUND_HOME=/opt/outbound OUTBOUND_PORT=${OUTBOUND_PORT:-8010}
ln -sfn "releases/$PREV" current
RELEASE=$PREV docker compose -p outbound -f "releases/$PREV/deploy/compose.yml" up -d --no-deps api worker
```

## 3. Fix

Find why the new release failed (its logs above), fix it in a new commit, and deploy. Never run `outbound db downgrade` in production: it can drop data, and the old code runs on the newer schema anyway.

## 4. Verify

```bash
curl -fsS "http://127.0.0.1:${OUTBOUND_PORT:-8010}/api/health"
oc ps -a
oc logs --since 5m worker | grep service_started
```

Then sign in to the web app, and check the Runs screen for a run stuck in `running` ([run stuck running](run-stuck-running.md)).

## 5. Follow up

A postmortem if the site was down during use. Push the R-01 fix ([register](../../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down)).
