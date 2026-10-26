---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Doppler token rejected, or Doppler unreachable

| | |
|---|---|
| **Severity** | SEV-2 |
| **Impact** | Containers cannot load secrets: a deploy fails, or a restart comes up with stale secrets. |
| **Signals** | `doppler.env is missing` (deploy preflight); `Doppler Error: … token` in container logs; containers exiting at start |
| **Related** | [Doppler](../../integrations/platform-doppler.md), [secrets](../../security/secrets-management.md) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --tail 50 api | grep -i doppler
ls -l /opt/outbound/doppler.env            # exists, mode 600, not empty
```
- `token` errors mean the token is wrong, revoked, or not a service token for `outbound/prd`.
- Network errors mean Doppler is unreachable. The containers then start from their fallback files on the `doppler` volume, with the last secrets they saw.

## 2. Contain

If Doppler is unreachable and the app is running, **do not deploy or restart** until it is back. A running container keeps its secrets.

## 3. Fix

**Token problem:**

1. In Doppler, create a new **service token** for `outbound/prd` with read access.
2. Update the GitHub `production` environment secret `DOPPLER_TOKEN`.
3. Run the deploy workflow; it rewrites `doppler.env`.
4. Revoke the old token.

**Outage:** wait; check Doppler's status page. A first deploy cannot work without Doppler, because there is no fallback yet.

## 4. Verify

`oc ps` shows the containers up; `oc logs --since 5m api` has no Doppler errors; sign in works.

## 5. Follow up

If the token leaked, follow [secret leaked](secret-leaked.md).
