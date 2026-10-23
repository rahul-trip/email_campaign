# Phase 5 — Automated sending

**Goal:** the engine sends approved touches itself, inside the send window and the daily caps. It stops automatically when deliverability degrades.

**Depends on:**
- Phase 4.
- The SaaS track: mailbox adapters from 6c; the `auto_send` plan feature from 6d. The send switch is per workspace.
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
- Sending through each connected mailbox's adapter (Graph, Gmail, SMTP for IMAP accounts).
- The send scheduler.
- The breaker.
- The preflight.
- The send switch.

**Out:** inbox rotation across several mailboxes. Add it only if volume grows past one mailbox's cap.

## Tasks

### 5.1 Send through each connected mailbox

**Decided with the SaaS track (2026-10-23):** each workspace connects its own mailboxes in 6c, so sending goes through the same adapters. There is no separate gateway product.

| Mailbox | How it sends |
|---|---|
| Microsoft 365 | Graph `sendMail`, with the `Mail.Send` scope added to the connection. SMTP basic auth is switched off by default for existing Microsoft tenants at the end of December 2026, so Microsoft 365 always goes through Graph |
| Google | Gmail `messages.send`, with the `gmail.send` scope. It is a *sensitive* scope, not a restricted one |
| IMAP accounts | SMTP with the same app password, through a new SMTP part of the IMAP adapter |

- **Smartlead and Instantly do not fit** a multi-tenant product: each customer would need its own account there.
- **EmailEngine stays an option** if holding many IMAP connections becomes a burden.
- **Automatic sending is a plan feature** (`auto_send`, 6d), switched on per customer by an admin.

- [ ] Add `send(message) -> rfc_message_id` to the `Mailbox` port (`providers/ports.py:235-252`) and implement it in each adapter.
- [ ] Bounces and replies keep coming through the Phase 4 inbox reading, so no business logic changes.

**Done when:** each adapter's `send` passes the same `Mailbox` contract tests (fixtures, no network), and one live send per mailbox type is recorded.

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
  - Warm-up has run for at least 14–21 days.

  The result is stored in `mailboxes.dns_check`.
- [ ] `settings.send_enabled` can only become true when the gate conditions above hold. The API refuses with the list of failing checks; every attempt is logged as an event.

**Done when:** the preflight tests use mocked DNS answers, and the switch refuses when any single condition fails.

## Gate record

- Date:
- Live send per mailbox type (Graph, Gmail, SMTP):
- Preflight result:
- Legal review (who, when, policy version):
- First 10 live sends (bounces, replies):
- Checked by:
