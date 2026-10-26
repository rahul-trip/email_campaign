---
type: reference
status: accepted
date: 2026-10-20
deciders: "@rahul-trip"
introduced_in: 3048c6b
---

# 0022. Consent belongs to the person who gave it

## Context

On a live lead the operator recorded the CEO's consent, but ranking preferred the CTO, so the draft went to the CTO and passed the country check on the CEO's consent, because consent was counted for anyone at the company.

## Decision

`policy_decision_for` takes the recipient. Before a recipient is chosen (the gate, the runner's guard) anyone's consent at the company keeps the lead moving. Once the email, copy or deliver step names the recipient, only **that person's** consent counts. People the operator chose (added them, gave their address, or recorded their consent) rank first.

## Consequences

- **Good:** consent is used as the law means it; the person the operator meant is the one written to.
- **Bad:** a lead can move past the gate on one person's consent and then hold at email or copy if a different person is chosen; the operator must pick the recipient ("Write to this person instead").
- **Follow-ups:** none.

## Alternatives considered

| Option | Why not |
|---|---|
| Company-level consent | Allows writing to someone who never consented |
| Require a recipient before the gate | The right person is often found only after research |

## Evidence in the code

- `outbound/stages/policy.py::policy_decision_for` (`recipient_id`); `outbound/domain/ranking.py::rank_contacts`; `outbound/services/leads.py::LeadService.change_recipient`.
- `tests/db/test_leads_and_settings.py` (recipient-only consent); `tests/domain/test_ranking.py`.
