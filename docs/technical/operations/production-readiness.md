---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Production readiness review

Is Outbound ready for routine live use? This review answers item by item, with evidence. It is for the Phase 3b gate and the first live runs, and it is repeated at every phase gate.

**Status:** ✅ ready · ⚠️ ready with a known limitation, accepted for now · ❌ not ready (blocks routine use) · ⏳ to verify.

**Verdict on 2026-10-21:** **not ready for routine unattended use; usable for supervised runs.** The operator can run the pipeline and approve emails safely, because the safety model and human approval hold. Deploys, scheduled work, cost accounting and recovery each have a gap that needs fixing or a manual workaround first. The blocking items are marked ❌.

## Safety and compliance

| Item | Status | Evidence |
|---|---|---|
| Suppression wins everywhere, checked again before each stage, at approval and at deliver | ✅ | [Safety model](../hld/safety-model.md); `tests/db/test_runner.py`, `tests/db/test_review_and_deliver.py` |
| Country rules, consent per recipient, skips acknowledged at approval | ✅ | [ADR 0019](../adr/0019-policy-block-holds-never-suppresses.md)–[0022](../adr/0022-consent-belongs-to-the-recipient.md); `tests/db/test_policy_skip.py`, `tests/db/test_verification_skip.py` |
| Human approval before any draft | ✅ | `web2/e2e/loop.spec.ts` |
| Sender profile reviewed before any email is written | ✅ | `CopyStage` precondition (Phase 3b A1) |
| Country rules reviewed by a lawyer | ❌ (needed before Phase 5) | `policy_seeds.py` has no reviewer ([PLAN §11](../../PLAN.md#11-compliance-and-deliverability)) |
| Forget, suppress and delete work from the app, the CLI and the API | ✅ | `tests/db/test_forget.py`, `tests/db/test_privacy.py`, `tests/db/test_delete_lead.py` |
| Subject-access requests can be answered | ⚠️ manual SQL | [R-23](../tech-debt-and-risks.md#r-23--p2--privacy-no-way-to-answer-a-subject-access-request) |
| Opt-outs by reply are processed | ⚠️ by hand until Phase 4 | [Safety model](../hld/safety-model.md#what-is-not-covered-yet) |
| Prompt injection contained | ⚠️ human approval holds; the fence has a gap | [R-08](../tech-debt-and-risks.md#r-08--p1--security-web-text-can-close-the-prompt-fence) |

## Correctness and recovery

| Item | Status | Evidence |
|---|---|---|
| A crash loses no lead and repeats no vendor lookup | ✅ | `tests/db/test_pipeline_e2e.py` |
| Operator edits always win | ✅ | `tests/db/test_runner.py::test_an_operator_edit_during_the_stage_wins_and_the_lead_is_tried_again` |
| Scheduled work runs: retries, catch-all answers, the Sent sync | ❌ | Nothing runs `tick` in production ([R-02](../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7)). Workaround: a cron entry on the VM ([runbook](runbooks/tick-not-running.md)) |
| A stopped worker's run is recovered; runs cannot overlap | ❌ | [R-05](../tech-debt-and-risks.md#r-05--p1--runs-a-stopped-worker-leaves-its-run-running-runs-can-overlap-b2-b3). Workaround: deploy only when no run is active |
| Backups exist and a restore has been rehearsed | ❌ | [Backup and DR](backup-and-dr.md); [R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3) |
| Migrations tested up and down on SQLite and Postgres | ✅ | `tests/db/test_migrations.py`; CI |

## Deploy and operate

| Item | Status | Evidence |
|---|---|---|
| Repeatable, one-click deploy from a commit, after CI | ✅ | `.github/workflows/deploy.yml` |
| Rollback works after a release that ran a migration | ❌ | Reproduced failure ([R-01](../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down)). Workaround: roll forward, or the manual procedure in [release and rollback](release-and-rollback.md#rolling-back), which still needs rehearsing |
| Health checks see the database and the worker | ❌ | [R-06](../tech-debt-and-risks.md#r-06--p1--operations-health-checks-do-not-see-a-broken-worker-or-database). Workaround: the post-deploy checks in [release and rollback](release-and-rollback.md#checking-a-release) |
| Deploy rehearsal works locally | ⏳ | `deploy/local-test.sh` exists; the manual rollback is not yet rehearsed |
| Runbooks for each known failure | ✅ | [Runbooks](runbooks/README.md) |
| Logs structured and free of secrets | ✅ | [Logging](../lld/logging.md) (client IPs are logged: [R-14](../tech-debt-and-risks.md#r-14--p2--privacy-personal-data-in-logs)) |
| Alerting | ⚠️ none; daily manual checks | [Observability](observability.md#what-to-watch) |
| SLOs agreed | ⏳ proposed | [SLOs](slos.md) |
| Database connections within the pooler limit | ⚠️ at the limit | [R-12](../tech-debt-and-risks.md#r-12--p2--capacity-the-connection-pool-fills-the-supabase-pooler); set `DATABASE_POOL_SIZE=3` |

## Cost

| Item | Status | Evidence |
|---|---|---|
| Every paid call metered, attributed and cached | ✅ | [Metering](../lld/metering.md); `tests/db/test_robustness.py` |
| Model spend counted | ❌ | `LLM_PRICES` must be set in Doppler ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)). A config fix, no code needed |
| Resolver submits counted by the cap | ⚠️ | [R-04](../tech-debt-and-risks.md#r-04--p1--cost-the-budget-cap-prices-a-catch-all-submit-at-0); set vendor-side caps |
| Vendor-side spending limits set in each vendor account | ⏳ | Operator to confirm |

## Vendors

| Item | Status | Evidence |
|---|---|---|
| Each vendor in the chain live-checked | ⚠️ | All verifiers, Tavily, the LLM, Companies House and IMAP pass; **Scrubby fails**; finders not yet checked live ([integrations](../integrations/README.md)) |
| Chain chosen by the bake-off | ⏳ | [R-09](../tech-debt-and-risks.md#r-09--p1--vendors-the-provider-chain-is-unproven-e5-d5) |

## Security

| Item | Status | Evidence |
|---|---|---|
| Threat model current | ✅ | [Threat model](../security/threat-model.md) |
| ASVS L1 self-assessment | ⚠️ 6 gaps | [ASVS checklist](../security/asvs-l1-checklist.md) |
| Secrets only in Doppler; rotation documented | ✅ | [Secrets](../security/secrets-management.md) |
| `SSH_KNOWN_HOSTS` set for the deploy | ⏳ | Operator to confirm ([GitHub Actions](../integrations/platform-github-actions.md)) |
| `production` environment requires a reviewer | ⏳ | Optional; operator to decide |
| HSTS at the proxy | ⏳ | Add to the VM's proxy configuration ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)) |

## To reach "ready"

In order:

1. **R-03:** set `LLM_PRICES` (configuration).
2. **R-01:** fix the rollback (start only `api` and `worker`, or let `migrate` accept a newer database).
3. **R-02:** schedule `tick` (a cron entry now; the worker ticks itself under B7).
4. **R-05:** deploy only when idle (now); then B2 and B3.
5. **R-07:** confirm Supabase backups, then do one restore drill.
6. **R-06:** a health check that touches the database; a check on the worker.
7. **Vendors:** replace or confirm Scrubby; run the bake-off.

## Sign-off

| Date | Reviewer | Verdict | Notes |
|---|---|---|---|
| 2026-10-21 | Documentation pass | Supervised use only | First review, from the code |
