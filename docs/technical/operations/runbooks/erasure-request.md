---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Someone asks to be erased, or asks what is held about them

| | |
|---|---|
| **Severity** | SEV-2 (legal deadline: one month) |
| **Impact** | A data-subject request under GDPR or the UK GDPR. |
| **Signals** | A reply or message asking to be removed, to stop, or for a copy of their data |
| **Related** | [privacy](../../security/privacy-data-processing.md), [data lifecycle](../../data/data-lifecycle.md), [R-23](../../tech-debt-and-risks.md#r-23--p2--privacy-no-way-to-answer-a-subject-access-request) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

Record the request (date received, how, the address), in the operator's own records. Do not put the address in tickets or chat.

- **"Stop emailing me" (objection):** Suppress the person.
- **"Delete my data" (erasure):** Forget.
- **"What do you hold about me?" (access):** see step 3.

## 2. Contain

Suppress at once on any such request: lead page → Suppress, or `outbound suppress <address>`. Unsent messages are cancelled and their drafts deleted.

## 3. Fix

**Erasure:** Forget the address: lead page → **Forget this person**, `POST /api/privacy/forget`, or `oc run --rm --no-deps api outbound forget <address> --yes`. If the result lists `drafts_left`, delete those drafts from the mailbox by hand.

**Access (no built-in export, R-23):** gather what is held with read-only SQL, scoped by workspace, and send it securely:

```sql
-- the person and their addresses
SELECT c.* FROM contacts c JOIN contact_emails e ON e.contact_id = c.id
WHERE c.workspace_id = :ws AND lower(e.email) = lower(:address);
SELECT * FROM contact_emails WHERE workspace_id = :ws AND contact_id = :contact_id;
SELECT basis, evidence, created_at, withdrawn_at FROM consents WHERE workspace_id = :ws AND contact_id = :contact_id;
SELECT subject, coalesce(final_body, generated_body) AS body, state, sent_at FROM messages
WHERE workspace_id = :ws AND contact_id = :contact_id;
SELECT body, created_at FROM notes WHERE workspace_id = :ws AND contact_id = :contact_id;
SELECT type, data, created_at FROM events WHERE workspace_id = :ws
  AND entity_id IN (:contact_id, /* their email and message ids */ :ids);
SELECT provider, operation, created_at FROM provider_calls WHERE workspace_id = :ws AND contact_id = :contact_id;
```

Also list where else their data went (the sub-processors in the privacy page).

## 4. Verify

- **Forget:** `tests/db/test_forget.py` proves the scrub. Search the lead page for the person: they show as forgotten. Adding the address again is rejected as suppressed.
- **Access:** the reply was sent within the deadline.

## 5. Follow up

Record the date completed. Erasure does not reach backups: re-apply it after any restore ([backup and DR](../backup-and-dr.md)).
