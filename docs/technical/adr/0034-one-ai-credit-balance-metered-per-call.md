---
type: reference
status: accepted
date: 2026-11-18
deciders: "@rahul-trip"
introduced_in: phase-6/ai-credits
supersedes: 0027
---

# 0034. One balance of AI credits per workspace, used by every vendor and model call

## Context

[ADR 0027](0027-credits-charged-once-per-lead-per-step.md) gave each plan a count per pipeline step (5 discovered leads, 5 added leads, …) charged once per lead. Customers saw counts on the Plan & usage page and dollars everywhere else (Reports, Runs, the lead page, the budget per lead). Model calls were not counted at all: no LLM price was set by default, so every model call was recorded at no cost.

The operator asked for one unit everywhere: **AI credits**. Three plans (Free, Starter, Pro) defined by superadmins, extra credits granted by admins, and every third-party vendor call and model call measured in AI credits, with each model charged at a rate the admin sets.

## Decision

- **One balance.** A plan gives a number of AI credits a month (`Plan.monthly_credits`). A grant adds AI credits to each period while it lasts. What is left is the monthly credits plus active grants minus what this period's calls used. Per-step limits are gone; `usage_events` stays as an activity count for reports.
- **Every call is measured when it is made.** `Meter.record` writes `provider_calls.credits_milli` (thousandths, so a small model call is not rounded to a whole credit):
  - a model call uses its model's charge (`PlatformSettings.llm_charges`: AI credits per million tokens in and out), set by staff on the Vendors page;
  - any other paid call converts its dollar cost at `PlatformSettings.credit_value_micro_usd` (default: one credit per US cent), set by a superadmin.
  The dollar cost stays on the row for the platform's books.
- **Past calls are not converted.** Rows written before migration 0029 keep `credits_milli = 0`, at the operator's request; only calls metered from now on count against a plan.
- **Who sets what.** Superadmins (`Permission.ADMIN_PLANS`) edit plans, the default plan and the credit rate. Platform admins grant credits, override a customer's settings and set model charges and vendor caps.
- **Where it stops work.** A stage that makes paid calls starts only while credits are left; otherwise the lead waits in place and resumes when credits are back. A started stage finishes. Discovery does not search, and rewrites are refused, without credits. The budget per lead and the console's vendor caps are in AI credits; the environment's monthly safety caps stay in dollars, as the platform's own guard.
- **What people see.** Customers see AI credits only. The console shows AI credits and, for staff, what the calls cost the platform in dollars, so margin is visible. The credit rate is the console's one dollar input.

## Consequences

- A model with no charge set uses no credits; the console warns until one is entered.
- A started stage may take the balance a little below nothing; the shortfall is small (one stage's calls) and accepted.
- Changing the rate or a charge never rewrites history: credits are fixed on the row.
- Billing (6e) sells plans and credit top-ups against `provider_calls.credits_milli`.
