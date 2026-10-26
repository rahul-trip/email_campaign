---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# A secret has leaked

| | |
|---|---|
| **Severity** | SEV-1 |
| **Impact** | Depends on the secret: spend (vendor and LLM keys), data access (`POSTGRES_URL`), mailbox access, session forgery (`SESSION_SECRET`), VM access (`DEPLOY_SSH_KEY`). |
| **Signals** | gitleaks failed in CI or pre-commit; a secret seen in a log, a paste, a screenshot or a commit; unexpected vendor spend; unknown logins |
| **Related** | [secrets management](../../security/secrets-management.md), [incident response](../incident-response.md) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

Identify **which** secrets and **where** they were exposed (commit, log, chat), and since **when**.

## 2. Contain

1. **Rotate first, clean up second.** Rotation steps for each secret are in [secrets management](../../security/secrets-management.md#inventory).
2. For a database or mailbox leak, consider stopping the worker until it is rotated.
3. For `SESSION_SECRET` or the operator password, rotate `SESSION_SECRET` to sign everyone out.

## 3. Fix

- **In a commit:** rotating is what matters, because the history is public to anyone who cloned it. Then remove it from the branch; rewriting history is optional and only helps if nobody has pulled.
- **In logs or chat:** delete them where you can.
- Check the vendor dashboards and the Supabase logs for use since the leak.

## 4. Verify

The old values no longer work (try them); the app and the worker run on the new ones; gitleaks is clean.

## 5. Follow up

A postmortem. If personal data could have been read (`POSTGRES_URL`, the mailbox), assess breach notification within 72 hours ([incident response](../incident-response.md#personal-data-breaches)).
