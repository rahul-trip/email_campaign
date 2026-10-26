---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Drafts are not saved, or the Sent sync fails

| | |
|---|---|
| **Severity** | SEV-3 |
| **Impact** | Approved emails stay `approved` (deliver defers them hourly); sent emails are not recorded. |
| **Signals** | Leads stuck in `approved` with `deferred` events; `job_failed` for `SentSync`; IMAP errors (`LOGIN failed`, timeouts, `APPEND … failed`) |
| **Related** | [IMAP mailbox](../../integrations/imap-mailbox.md), [deliver and sync](../../lld/stage-deliver-and-sync.md) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --since 6h worker | grep -iE 'imap|"stage": "deliver"' | tail -20
```
```sql
SELECT entity_id, created_at, data FROM events
WHERE workspace_id = :ws AND type = 'deferred' ORDER BY created_at DESC LIMIT 20;
```
Check that `IMAP_HOST`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `DRAFTS_FOLDER` and `SENT_FOLDER` are right for the provider (folder names differ, for example `INBOX.Drafts` against `Drafts`).

## 2. Contain

Nothing: approved emails wait safely and are drafted once the mailbox works. Drafting is idempotent.

## 3. Fix

Fix the login (a new app password), or the folder names, in Doppler; restart the worker. If the provider moved to OAuth-only, a new adapter is needed.

## 4. Verify

The next run's deliver stage moves leads to `in_sequence`; drafts appear in the mailbox; `uv run python -m scripts.live_check --only imap` passes.

## 5. Follow up

—
