---
type: reference
status: accepted
date: 2026-10-21
deciders: "@rahul-trip"
introduced_in: 87b4e38 (migration 0004)
---

# 0020. Skipping a country rule is per lead, from one stage onward, or for the whole workspace

## Context

The operator sometimes knows a contact is lawful where the engine cannot prove it (an existing relationship, a confirmed corporate subscriber). They asked to skip the country rule for a lead at chosen stages, or to switch rules off for the workspace. Skipping an arbitrary set of stages could let a later stage contradict an earlier one.

## Decision

`companies.policy_skip_from` names one `PolicyStage` (`gate`, `contacts`, `email`, `copy`, `deliver`); the rule is skipped at that stage and **every later one** (a tail). `workspaces.settings.country_policy_enabled = false` skips every rule for the workspace. Either way the decision is ALLOW with `skipped = true`, the reason is recorded (`policy_skip_granted`), suppression still applies, and the footer follows its own setting. A lead the rule stopped resumes where it stopped; the skip can be revoked until approval.

## Consequences

- **Good:** the operator's judgement is possible, explicit and audited; no stage disagrees with a later one; suppression is untouched.
- **Bad:** a skipped rule moves legal responsibility to the operator; the app shows a red banner while rules are off, and approval must acknowledge the skip ([ADR 0021](0021-skips-acknowledged-at-approval.md)).
- **Follow-ups:** Phase 5 must not send automatically when a skip applies.

## Alternatives considered

| Option | Why not |
|---|---|
| A skip flag per stage | Arbitrary sets allow contradictions |
| Edit the country rule instead | Changes every lead in that country, not this one |

## Evidence in the code

- `outbound/domain/policies.py::policy_skipped_at`, `skipped_decision`; `outbound/stages/policy.py::policy_decision_for`; `outbound/services/leads.py` (`skip_policy`, `revoke_policy_skip`, `release_policy_holds`); migration `0004_policy_skip`.
- `tests/db/test_policy_skip.py`.
