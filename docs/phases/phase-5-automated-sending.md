# Phase 5 — Automated sending

**Goal:** the engine sends approved touches itself, inside the send window and the daily caps. It stops automatically when deliverability degrades.

**Depends on:**
- Phase 4.
- Three prerequisites outside the code:
  - a separate sending domain with SPF, DKIM and DMARC configured;
  - a lawyer's review of `country_policies` and of the legitimate-interests assessment;
  - an always-on host.

**Gate:** the send switch can only be turned on when all of these hold:
- Gate 2 has passed (copy quality).
- Gate 4 has passed (reply handling).
- The DNS and warm-up preflight is green.
- Every allowed country policy row has `reviewed_by` set.

Then send to 10 real prospects at the starting cap and confirm the breaker logic against the live counts.

## Scope

**In:**
- Choosing the sending gateway and writing its adapter.
- The send scheduler.
- The breaker.
- The preflight.
- The send switch.

**Out:** inbox rotation across several mailboxes. Add it only if volume grows past one mailbox's cap.

## Tasks

### 5.1 Choose and build the sending gateway

- [ ] Decide between:
  - **EmailEngine** (self-hosted Docker, REST, bounce and sent webhooks);
  - **Smartlead or Instantly** (about $37–39 a month, includes peer-to-peer warm-up).

  If warm-up is not otherwise available, Smartlead or Instantly is the simpler choice. Record the decision in [../PLAN.md](../PLAN.md) decision 10.
- [ ] Write `adapters/<gateway>.py` implementing `MailboxGateway.send(message) -> rfc_message_id`, plus that gateway's events for sent, bounce and reply.
- [ ] Webhooks from the gateway feed the same Phase 4 handlers, so no business logic changes. IMAP polling stays available as a fallback.

**Done when:** the gateway adapter passes the same `MailboxGateway` contract tests as the IMAP adapter.

### 5.2 Send scheduler

- [ ] Approved touches get `scheduled_for` inside the window: **Tuesday–Thursday, 08:00–10:30, in the prospect's time zone**.
  - Time zone comes from `country_code`.
  - For countries with several zones, use the zone in `research` if one was found, otherwise the country's main business zone (for the US, Eastern).
- [ ] `outbound tick` sends messages that are due, up to `mailboxes.daily_cap`, with random gaps of 45–120 seconds. Drafts never wait.
- [ ] Warm-up ramp: the daily cap starts at 10–20 and rises by hand to about 50 over roughly four weeks. The UI shows the current cap and days since warm-up started.
- [ ] Every send re-runs the guards and `is_safe_to_send` first.

**Done when:** window and cap tests pass across time zones and over a weekend boundary.

### 5.3 Breaker

- [ ] Pause sending for a mailbox when either holds:
  - 3 or more hard bounces in its last 100 sends;
  - 2 or more hard bounces within 24 hours.

  Soft bounces are excluded.
- [ ] A pause sets the mailbox to `paused`, writes an event, and shows a banner in the UI. Only an operator can resume.

**Done when:** breaker tests pass for each threshold, including that soft bounces don't count.

### 5.4 Preflight and send switch

- [ ] `services/preflight.py`. Checks:
  - SPF is valid and needs no more than 10 DNS lookups.
  - The DKIM selector resolves.
  - DMARC is set to `quarantine` or `reject`, with an `rua` address.
  - The sending domain is not the workspace's primary domain.
  - Warm-up has run for at least 14–21 days, or is active in the gateway.

  The result is stored in `mailboxes.dns_check`.
- [ ] `settings.send_enabled` can only become true when the gate conditions above hold. The API refuses with the list of failing checks; every attempt is logged as an event.

**Done when:** the preflight tests use mocked DNS answers, and the switch refuses when any single condition fails.

## Gate record

- Date:
- Gateway chosen:
- Preflight result:
- Legal review (who, when, policy version):
- First 10 live sends (bounces, replies):
- Checked by:
