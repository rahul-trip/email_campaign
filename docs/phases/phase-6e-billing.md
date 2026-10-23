# Phase 6e — Billing (after the alpha)

**Status:** not in the alpha. The alpha has no payments; staff assign plans and invoice outside the app (6d). This document keeps the research so the work can start without repeating it.

**Goal:** customers start a trial, pay by card, change plan and update their payment details themselves. A failed payment ends in read-only access, never in lost data.

**Depends on:** 6d.

**Gate:** the test-mode lifecycle passes against recorded webhook fixtures, and once end to end in staging:

trial → paid → payment fails → grace → read-only → payment recovered

## Decisions to take first

**Who bills.** This depends on where the selling company is incorporated.
- **Stripe Billing with Stripe Tax:** we are the merchant, and we register for VAT/GST where needed.
- **A merchant of record** (Stripe Managed Payments, or Paddle): they handle indirect tax.
  - Stripe Managed Payments accepts sellers based in the US, Canada, the UK, most of Europe, Australia, Hong Kong, Japan and Singapore. India is not on its list.
  - It creates subscriptions only through Checkout or Payment Links, which fits the design below.

**Prices and credits.** Set after the bake-off has measured the cost per safe email. Keep each price at least 3× the measured cost per lead.

## Design

- **Checkout:** Stripe Checkout starts a subscription, and the Customer Portal handles card changes, plan changes, cancellation and invoices.
- **Plans:** `workspace_plans` gains `provider` (`manual`, `stripe`) and the Stripe customer and subscription ids.
- **Webhooks:**
  - `checkout.session.completed`, `customer.subscription.*`, `invoice.paid` and `invoice.payment_failed` update `workspace_plans`;
  - `billing_events` (a new table) stores each provider event id once, so a replayed webhook changes nothing.
- **Usage:** `usage_events` (6d) are reported to Stripe meters, keyed by `usage_events.id`. This is needed only if overage is sold.
- **Dunning:**
  - Stripe retries the payment;
  - for 7 days the customer has full access with a banner;
  - then the workspace is read-only (`access_level`);
  - recovery reopens it, and waiting work resumes (6d).
- **Open sign-up and its abuse controls:**
  - disposable-domain blocking;
  - email verification;
  - a CAPTCHA (its origin added to the content security policy);
  - trial credit limits.

## Tests that must exist

- Webhook fixtures for each event: idempotent, and in the right order.
- The dunning timeline with a fixed clock.
- Plan changes up and down; an over-limit downgrade deletes nothing.

## Gate record

- Date:
- Billing provider chosen:
- Lifecycle test (fixtures, staging):
- Checked by:
