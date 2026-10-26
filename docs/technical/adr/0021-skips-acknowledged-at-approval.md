---
type: reference
status: accepted
date: 2026-10-21
deciders: "@rahul-trip"
introduced_in: f76b255 (migration 0005)
---

# 0021. Every skipped check is acknowledged at approval, and never sent automatically

## Context

With skips for the country rule, address verification and person confirmation, an email can reach the mailbox relying on the operator's word rather than the engine's proof. The skip may have been made days earlier, for a different reason, or by mistake.

## Decision

Approval lists every skip the email relies on (`country_policy`, `email_verification`, `works_here`) and is refused unless the operator acknowledges them (`acknowledge_skips`; a required tick box on Review, `--acknowledge-skips` on the CLI). The acknowledgement is recorded as an `approved_with_skips` event with the kinds. Automatic sending (Phase 5) must never send a message that relies on a skipped check; such a message always waits for a person.

## Consequences

- **Good:** a skip is confirmed at the moment it matters, by the person who will send; the audit trail shows what was knowingly allowed.
- **Bad:** one more click per skipped email; Phase 5 must carry the rule.
- **Follow-ups:** Phase 5 sending must check for `approved_with_skips` or recompute the skips.

## Alternatives considered

| Option | Why not |
|---|---|
| Trust the skip once made | Stale or mistaken skips reach the mailbox unnoticed |
| Forbid skips | The operator could not proceed with leads they know are lawful |

## Evidence in the code

- `outbound/services/review.py::ReviewService.approve`, `_skips`; `contact_emails.verification_skipped` (migration `0005_verification_skipped`).
- `tests/db/test_verification_skip.py`; `web2/e2e/loop.spec.ts`.
