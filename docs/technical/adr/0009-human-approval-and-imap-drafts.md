---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §3](../../PLAN.md#3-decisions-all-confirmed) decisions 10, 12; c3d3228 (#1)
---

# 0009. A human approves every first email, and the engine only saves drafts over IMAP

## Context

Generated emails can be wrong in ways a linter cannot see: a false claim, the wrong person, a tone problem. Sending is the irreversible step, and compliance rules differ per country. The operator already uses an ordinary mailbox, and choosing a sending gateway is deferred to Phase 5.

## Decision

Until Phase 5, no email leaves without a person. The engine writes touch 1, the operator approves it (on the Review screen or the CLI), and the deliver stage saves it as a draft in the operator's mailbox over IMAP, with a deterministic `Message-ID` so a retry never duplicates it. The operator sends it by hand; a Sent-folder sync records what actually went out and how much it was edited.

## Consequences

- **Good:** a person is the final control against every failure mode upstream, including prompt injection; the operator's real mailbox keeps their sending reputation and threading; edits become training examples.
- **Bad:** throughput is bounded by the operator's time; IMAP is slow and has no retries in the HTTP client; the Sent sync needs a scheduler ([R-02](../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7)).
- **Follow-ups:** Phase 5 must keep emails that rely on skipped checks out of automatic sending ([ADR 0021](0021-skips-acknowledged-at-approval.md)).

## Alternatives considered

| Option | Why not |
|---|---|
| Send directly via SMTP or an API from Phase 2 | Irreversible before the copy quality gate (8 of 10 unedited) is met |
| A sending platform (Smartlead, Instantly) now | Deferred to Phase 5 behind the mailbox port |

## Evidence in the code

- `outbound/services/review.py::ReviewService.approve`; `outbound/stages/deliver.py::DeliverStage` (`draft_message_id`, `draft_exists`, `append_draft`, `undo`).
- `outbound/stages/sync.py::SentSync`; `outbound/providers/adapters/imap_mailbox.py`.
