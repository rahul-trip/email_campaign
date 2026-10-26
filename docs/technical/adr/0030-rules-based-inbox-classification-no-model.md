---
type: reference
status: accepted
date: 2026-10-26
deciders: "@rahul-trip"
introduced_in: f61abc3
---

# 0030. Reply classification is rules-only until a later phase, and only two categories act automatically

## Context

Once drafts are sent, replies start arriving, and two kinds cannot wait for a human to read them: an opt-out, which the law and sender reputation both require stopping on immediately, and a hard bounce, which means the address is dead and the engine should move on to another contact. A full reply classifier (interested, not interested, wrong person, forward me to someone else) is valuable but is explicitly later-phase work; Phase 4a needs just the two time-critical categories, reliably and cheaply.

## Decision

Classification (`outbound/domain/inbox.py::classify`) is pure regex, with no model call: a fixed, ordered set of checks for `HARD_BOUNCE`/`SOFT_BOUNCE` (by sender address pattern plus subject/status-code wording), `OUT_OF_OFFICE`, and `UNSUBSCRIBE` (checked only against the sender's own words, with quoted text stripped first, so a reply quoting our own footer's unsubscribe wording back at us is not misread). Only `HARD_BOUNCE` and `UNSUBSCRIBE` trigger an automatic action (`PrivacyService.bounced`/`suppress_contact`, under the `SYSTEM` actor), and only when the reply is matched — by threading headers first, then by the bounce's failed-recipient address or the sender address, always against addresses this workspace actually sent to — to a specific contact. `OUT_OF_OFFICE` and everything else (`OTHER`) are recorded for a human to see on the lead's timeline, with no automatic action.

## Consequences

- **Good:** deterministic — the same message text always gets the same answer, with no model cost, no model latency, and no model-introduced inconsistency on the two categories that matter most for compliance and deliverability. Matching only against addresses actually sent to means a same-named person at an unrelated company, or stray mail that happens to mention "unsubscribe," cannot trigger an action on the wrong lead.
- **Bad:** anything short of exact bounce/opt-out phrasing patterns (an opt-out phrased unusually, a bounce from a mail server whose notification format the regex set does not recognise) falls through to `OTHER` and waits for a human — correct-by-default (never wrongly acts) but means some genuine opt-outs are caught later than they ideally would be, by a person reading the lead's timeline rather than automatically.
- **Follow-ups:** classification confidence is computed but not yet used to gate action — any match, at any confidence, acts immediately; gating low-confidence matches behind a human confirmation step is explicitly deferred, as is a model-based classifier for the richer categories `OTHER` currently absorbs.

## Alternatives considered

| Option | Why not |
|---|---|
| A model-based classifier from the start | More flexible to phrasing, but non-deterministic, adds cost and latency to every inbound message, and is unnecessary complexity for the two categories Phase 4a actually needs to act on |
| Act on any reply matching opt-out/bounce wording, regardless of address match | Risks acting on a wrong lead whenever the same wording appears in an unrelated reply; matching-by-address-actually-sent-to is a cheap, high-value guard |

## Evidence in the code

- `outbound/domain/inbox.py` (`classify`, `_own_words`, the regex constants).
- `outbound/services/inbox.py::InboxSync` (`_match`, `_handle`, idempotency via `rfc_message_id` and the one-hour overlap window).
- `tests/domain/test_inbox.py`, `tests/services/test_inbox_sync.py`.
