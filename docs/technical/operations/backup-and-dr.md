---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Backup and disaster recovery

**Status: not in place.** No backup or restore procedure has been set up or tested ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3), Phase 3b E3). This page states the recovery targets, where the state lives, and the procedures to adopt. Each procedure is marked "to verify" until it has been rehearsed once.

## Proposed targets

| | Target | Why |
|---|---|---|
| **RPO** (data you can afford to lose) | ≤ 24 hours | Losing a day means re-adding a few leads and re-researching them. Vendor answers are lost with the ledger, so some calls would be paid again |
| **RTO** (time to be working again) | ≤ 4 hours | One operator; no sending happens without them |
| **Erasure and suppression** | Must survive any restore | A restore must not bring back a forgotten person or let a suppressed address be written to |

## Where state lives

| State | Where | Loss means | Recovered from |
|---|---|---|---|
| **Everything the engine knows**: leads, people, consents, messages, events, ledger, settings, suppressions | Supabase Postgres | The business record, the audit trail, consents and suppressions | Supabase backups (below) |
| Secrets | Doppler (plus encrypted fallbacks on the VM's `doppler` volume) | No restart possible | Doppler; rotate if lost ([secrets](../security/secrets-management.md)) |
| Drafts and sent mail | The mailbox provider | Drafts can be re-made by deliver; sent mail is the operator's | The mailbox provider |
| Code and releases | GitHub; release folders and images on the VM | Nothing: rebuild from a commit | GitHub |
| Logs | Docker on the VM | Diagnostics only | — |
| Development data | `outbound.db` on a laptop | Development work | `sqlite3 outbound.db ".backup 'copy.db'"` |

## Database backups

**What Supabase provides depends on the plan.** Check the project's dashboard (Database → Backups) and record the answer here:

- [ ] Daily backups, and how long they are kept: ______
- [ ] Point-in-time recovery available: yes / no; window: ______
- [ ] Who can restore (dashboard access): ______

**An independent logical backup.** To verify. This protects against losing the Supabase account or project, and gives a copy you control. Run it from a trusted machine or the VM:

```bash
# Uses the same POSTGRES_URL as production (session pooler). Store the file encrypted:
# it contains personal data (see privacy-data-processing.md).
pg_dump --format=custom --no-owner --no-privileges "$POSTGRES_URL" \
  --file "outbound-$(date -u +%Y%m%dT%H%MZ).dump"
```

Keep at most the retention you can justify (personal data), for example 7 daily and 4 weekly. **A backup taken before an erasure still holds the erased person.** Expire backups on schedule, and re-apply erasures after any restore (below).

## Restore

To verify; rehearse into a scratch Supabase project first.

1. **Stop writes.** `oc stop worker api`, so nothing writes during the restore.
2. **Restore the database.** Use the Supabase dashboard restore (or PITR) for the project. Alternatively, restore a dump into an empty project:

   ```bash
   pg_restore --no-owner --no-privileges --dbname "$NEW_POSTGRES_URL" outbound-<stamp>.dump
   ```

3. **Point production at it, if the project changed.** Update `POSTGRES_URL` in Doppler `prd`.
4. **Check the schema.** `oc run --rm --no-deps api outbound db current` must show the revision the deployed code expects. `outbound db upgrade` brings an older backup forward.
5. **Re-apply erasures and suppressions made after the backup.** Find every `forgotten` and `suppression_added` event in the old database (or the operator's records) dated after the backup, and run them again: `outbound forget <email>` and `outbound suppress <value>`. **Do not skip this step.**
6. **Start and check.** `oc start api worker`, then follow the checks in [release and rollback](release-and-rollback.md#checking-a-release).
7. **Reconcile the mailbox.** Drafts in the mailbox for messages that the restored database shows as `approved` will be found by `Message-ID`, and not duplicated, on the next deliver.

## Disaster scenarios

| Scenario | Recovery |
|---|---|
| The VM is lost | A new VM, then [deployment §1](deployment.md#1-one-time-setup) and a deploy of the last good commit. The data is in Supabase. RTO is about 1–2 h |
| The Supabase project is lost or corrupted | Restore, as above. RTO is hours; RPO is set by the backup |
| Doppler unreachable | Containers restart from their fallback files; deploys wait ([runbook](runbooks/doppler-token-or-outage.md)) |
| A secret leaked | [Secret leaked](runbooks/secret-leaked.md) |
| A bad migration or data change | Roll forward with a fix if possible; restore if not; data fixes follow [data fixes](data-fixes.md) |

## Drill

Once before live use, then every quarter:

1. Restore the latest backup into a scratch project.
2. Run `outbound status` against it.
3. Time it.
4. Record the date and duration here.

| Date | Backup used | Time to working | Notes |
|---|---|---|---|
| — | — | — | Not yet done |
