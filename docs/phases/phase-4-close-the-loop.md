# Phase 4 — Close the loop

**Goal:** after touch 1 goes out, the engine handles everything that comes next: it follows up on schedule, reads replies and acts on them, handles bounces and opt-outs, and hands positive replies to the operator's tools.

**Depends on:** Phase 3. An always-on host is needed from here, because `outbound tick` and the worker must run continuously.

**Built after the SaaS foundation (6a–6d)**, so it is tenant-aware from the start:
- Inbox reading, handlers and webhooks work per workspace and per mailbox.
- The mailbox adapters come from 6c (IMAP, Microsoft Graph, Gmail), through the `MailboxResolver`. The reply webhook URL and its secret are per workspace.

**Split for the alpha:**
- **4a** comes *before* the alpha, because every footer already promises that an opt-out is honoured:
  - reading replies (4.2) for the `unsubscribe` and `hard_bounce` categories;
  - their handlers (4.3).

  Its gate: an "unsubscribe" reply and a hard bounce each suppress the address and cancel pending emails, on fixtures and on one live mailbox.
- **The rest of Phase 4** follows the alpha, in parallel with 6g.

**Gate:**
- A reply cancels every pending touch for that lead.
- A referral reply creates a new rank-0 contact that goes through verification automatically.
- Tested on fixture mailboxes, then on a live mailbox with one test lead.

> **4a as built (2026-10-26):** `outbound/domain/inbox.py` classifies by rule (hard and soft bounce, opt-out, auto-reply, other); `outbound/services/inbox.py` (`InboxSync`, a tick job) reads each mailbox, matches mail to our emails by threading headers, then by the bounced or sending address, and ignores everything else without keeping it. An opt-out runs `PrivacyService.suppress_contact`; a hard bounce runs `PrivacyService.bounced` (address invalid, suppressed, sent message `bounced`, drafts deleted, lead on to the next person). **Not in 4a:** the model classifier, positive, question, referral and out-of-office handling, soft-bounce retry, the Replies screen, and a test on a live mailbox. Tests: `tests/domain/test_inbox.py`, `tests/db/test_inbox_sync.py`.

## Scope

**In:**
- Follow-ups written just in time, still saved as drafts.
- Inbox classification into six categories, plus `other`.
- Hard and soft bounce handling.
- Out-of-office snoozing.
- Opt-out suppression.
- Referral capture.
- Webhook on positive reply.
- Export.
- Wiring up the forget action end to end.
- The Replies screen.

**Out:** sending by the engine itself (Phase 5).

## Tasks

### 4.1 Follow-up scheduling (just in time)

- [ ] When the Sent sync marks a touch `sent`, set `companies.next_action_at` to the next offset in `campaign.cadence_days`. Offsets are business days from touch 1 and default to 0, 3 and 8. The clock starts at the confirmed `sent_at`, not at draft creation.
- [ ] When the follow-up is due, `outbound tick` runs the copy subgraph for step 1 or 2 with the full thread as context, writing 25–50 words. The result is a `messages` row with subject `Re: <touch-1 subject>` and `in_reply_to` = the previous touch's `rfc_message_id`.
  - Phase 4: it goes into the review queue, is approved, then drafted.
  - Phase 5: it is sent through the gateway.
- [ ] Threading headers on drafts: `In-Reply-To` and `References`, both taken from the confirmed sent Message-ID.
- [ ] After the last touch, if there is still no reply, set the lead to `completed`.

**Done when:** the timing tests pass, including a draft left unsent for 4 days, which delays its follow-up rather than shortening the gap.

### 4.2 Inbox classification

- [ ] `outbound tick` reads INBOX since the last sync through `MailboxGateway.list_inbox`.
- [ ] It matches each message to an outbound message using `In-Reply-To` and `References` first, then sender address, then sender domain (a colleague may reply instead of the contact).
- [ ] Classification order:
  1. Headers: `Auto-Submitted`, `X-Auto-Response-Suppress` and DSN content types.
  2. The DSN status code (5.x.x is hard, 4.x.x is soft).
  3. An LLM classifier through `Metered`, used only for the rest.
- [ ] Each result is stored in `inbound_messages` with its category, confidence and extracted fields.

**Done when:** the classifier fixtures cover every category, with at least 3 real-world samples each.

### 4.3 Category handlers

| Category | Action |
|---|---|
| `positive` | Lead → `replied`; cancel pending touches; fire the reply webhook; show at the top of Replies |
| `question` | Lead → `replied`; cancel pending touches; draft a suggested answer from the sender profile into the review queue |
| `referral` | Contact → `referred_away`; insert the referred person at rank 0, source `referral`; append the note "Referred by …"; lead → `contacts_found`, so Email and Copy run again with the referral as the hook |
| `out_of_office` | Keep status; parse the return date; set `next_action_at` = return date + 2 business days. If an alternate contact is named, store it as `ooo_alternate` without replacing the primary |
| `unsubscribe` | Add the email hash (and the domain hash, if asked) to `suppressions`; lead → `suppressed`; cancel pending touches and delete their drafts from the mailbox |
| `hard_bounce` | Email → `invalid`; contact → `bounced`; add the email hash to suppressions; lead → `contacts_found` for the next contact |
| `soft_bounce` | Retry once after 48 hours; if it bounces a second time, treat it as hard |
| `other` | Shown in Replies for the operator to decide |

Once the verified lead directory exists (6g), a `hard_bounce`, or a reply saying the person has left, also disputes that fact in the directory. A `referral` adds an observation.

**Done when:** there is one end-to-end test per category on fixture mailboxes.

### 4.4 Hand-off, export and forget

- [ ] **Reply webhook.** On `positive`, POST a JSON payload to `settings.reply_webhook_url`. The payload holds the research summary, answers, contact fields (both operator and engine values) and the full thread. It is signed like the intake webhook and retried with backoff.
- [ ] **Export.** `GET /exports/replied` returns CSV, and the Replies screen has a button for it.
- [ ] **Forget.** `POST /api/forget` with an email, plus the CLI `outbound forget EMAIL`. This runs the Phase 1 forget service, then deletes any unsent drafts from the mailbox.

**Done when:** after forget, a scan of every text column and of `provider_calls.response` finds no trace of the address.

### 4.5 Replies screen

- [ ] Inbound messages grouped by category; suggested answers for questions; one-click export; and an override when the classifier got the category wrong. An override re-runs that category's handler.

## Gate record

- Date:
- Fixture results by category:
- Live test (reply stops sequence, referral auto-created):
- Checked by:
