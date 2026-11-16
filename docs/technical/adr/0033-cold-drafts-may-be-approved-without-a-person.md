---
type: reference
status: accepted
date: 2026-11-16
deciders: "@rahul-trip"
introduced_in: phase-6/operator-experience
---

# 0033. Cold drafts may be approved without a person, when a workspace switches it on

## Context

[ADR 0009](0009-human-approval-and-imap-drafts.md) makes a person approve every email before it becomes a draft in the mailbox. In use, most of a day's review is spent on leads that fit the campaign only just (the fit score is a number from 0 to 100 and the default minimum is 60). The operator asked for the leads that fit best to stand out, and for the rest to reach the mailbox's Drafts folder without waiting in Review.

Nothing here changes who sends: the engine never sends (`send_enabled` cannot be switched on), so the person still reads every draft in their mailbox and presses Send.

## Decision

- **Hot and cold.** A fit score above 80 is **hot** (`domain.qualification.is_hot`; the API's `CompanyOut.hot`). 80 or lower is **cold**. A lead with no score is neither.
- **A workspace setting, off by default.** `auto_approve_cold`. With it on, the worker's tick runs `services.autoapprove.AutoApprover`, which approves the email of each cold lead through `ReviewService.approve`, the same code a person uses, as the actor `auto`. The suppression check, the state machines, the events and the deliver stage's safety gates therefore all apply unchanged.
- **What it never approves.** A hot lead's email, an email whose lead has no score, and an email that relies on a check someone skipped (approving that is where a person confirms the skip, [ADR 0021](0021-skips-acknowledged-at-approval.md)). It does approve an email the writing check flagged: that was the operator's choice.
- **It is visible.** The email's history says *Approved automatically (cold lead)*; the bell says how many were approved; the actor is `auto`, which `is_operator` does not treat as an operator, so [operator input wins](0011-operator-input-wins.md) is unaffected.
- **It does not teach or score itself.** The "sent without edits" figure on Reports leaves out emails approved by `auto`, because no person chose them; the writer's earlier-edits examples already use only emails a person edited.

## Consequences

- With the switch on, an unread email can reach a mailbox's Drafts folder. The risk is recorded as R-43 in the register: read cold drafts in the mailbox before sending.
- The threshold (80) is a constant, not a setting. Changing it is a one-line change with a test.
- Turning the switch off stops new automatic approvals at once; emails already approved and drafted stay.
