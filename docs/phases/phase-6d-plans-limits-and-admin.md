# Phase 6d — Plans, limits, credits and the admin console

**Goal:** platform admins manage every customer from one console:
- plan, per-step limits, extra credits and access time;
- features, including skipping the lead directory;
- the third-party API keys.

Customers see their usage. A lead stopped by a limit resumes by itself as soon as credits exist.

**Depends on:** 6c (and 6b for roles).

**Gate:**
- **Free plan:**
  - a 6th manual lead in a month waits, and after an admin grants credits it resumes by itself;
  - a 6th discovered lead is never searched for.
- **Mid-pipeline:**
  - a lead whose next step has no credit waits at that step and resumes by itself when credits appear;
  - **Resume** refuses without credits and says when they reset.
- **No double charges:** research again, retries and reruns charge nothing for a step already charged on that lead.
- **No restarts:** an admin changes a limit or replaces a vendor key, and the next step uses it.
- **Audit and access:**
  - every admin change and every key reveal is in the audit log;
  - a suspended customer cannot run;
  - a workspace past its access date is read-only, and continues where it stopped once access is extended.
- **Alpha gate:** two pilot customers are onboarded by invitation, and a month of recorded vendor spend matches the vendors' invoices within ±5%.

## Scope

**In:**
- the plan catalog;
- each customer's plan, access period, overrides and grants;
- usage per step;
- waiting and resuming;
- the Plan & usage page and "Ask for more credits";
- the admin console (nine screens);
- vendor keys and model settings in the database;
- platform settings (kill switch, caps, superadmin switch);
- email notices.

**Out:** payments and trials (6e, after the alpha).

## Steps and credits

| Step | Charged when | Free plan |
|---|---|---|
| `discovery` | A discovered company is accepted as a new lead | 5 a month |
| `manual` | A company added by a person (form, upload, webhook) is accepted as a new lead. A merge into an existing lead is free | 5 a month |
| `research` | `new → researched` succeeds | no limit |
| `email` | `contacts_found → email_ready` succeeds | no limit |
| `copy` | `email_ready → copy_ready` succeeds | no limit |
| `deliver` | `approved → in_sequence` (the draft is in the mailbox) | no limit |
| `rewrite` | Each "Write it again" or "Ask for changes" | no limit |

**Charging rules:**
- **Once per lead per step.** `usage_events` has a unique key (workspace, step, company), so retries, research again and reruns never charge twice.
  - `rewrite` is the only step that can repeat.
  - A deleted lead keeps its usage rows, with no foreign key, so usage cannot be reset by deleting.
  - The per-prospect budget still caps vendor spend on any one lead.
- **Who writes the charge:**
  - pipeline steps: `Runner._apply` (`runner/runner.py:232`), in the same transaction as the step's result;
  - `discovery` and `manual`: `IntakeService` (`services/intake.py`), when it accepts a row;
  - `rewrite`: `ReviewService`.
- **Available on a step** = the plan's limit, or the customer's override, + active grants − this period's usage.
- **The period** is monthly, counted from the day the customer's plan started.
- **Pure functions** in `outbound/domain/entitlements.py`:
  - `effective_entitlements(plan, overrides, now)`;
  - `available(step, entitlements, grants, used)`;
  - `access_level(workspace_status, workspace_plan, now)`, which returns `full`, `read_only` or `locked`.

## Waiting and resuming

**Where work waits:**
- **Manual rows over the limit are not rejected.** They stay `pending` import rows with the reason `waiting_for_credits`. No schema change is needed.
- **Discovery** asks the search only for as many companies as credits allow, and shows a notice. It never searches for leads it cannot add.
- **Pipeline steps:**
  - The runner's guard (`runner/guards.py:35-63`) refuses a step that has no credit.
  - The lead **keeps its status** and gets `companies.credit_wait_step`, plus one `waiting_for_credits` event.
  - `CompanyRepository.due` (`db/repositories/companies.py:95-108`) skips leads that are waiting.
  - **Why not a hold:** a hold resumes at a fixed status per reason (`_HELD_RESUMES` in `domain/state_machines.py`), `new → held` is not an allowed move, and holding an approved lead withdraws its email. Waiting in place needs no state-machine change and loses nothing.

**How it resumes:**
- **Automatically:** a tick job runs per workspace. As soon as credits exist (a new period, a grant, a raised limit, extended access), it releases the oldest waiting leads and rows, never more than the credits available. Each gets one `resumed` event.
- **By hand:**
  - **Resume** on a lead, and **Resume all** on Needs attention and Add leads; an admin can do the same for any customer;
  - each checks credits first;
  - without credits, it says when they reset and offers **Ask for more credits**.

**Access:** past `access_until` the workspace is read-only, and nothing is lost. Extending access reopens it, and the worker continues where it stopped. Other stops resume as before: failed leads retry and other holds release.

## Tasks

### 6d.1 Migration 0012

**Read by the customer, written by platform admins:**
- [x] `workspace_plans`: one per workspace; `plan_code`, `started_at` (the period anchor), `access_until`, `note`.
- [x] `entitlement_overrides`: `key`, `value` (JSON), `expires_at`, `note`, `set_by`, `created_at`, `revoked_at`.
- [x] `credit_grants`: `step`, `amount`, `expires_at` (end of period, a date, or null), `note`, `granted_by`, `created_at`, `revoked_at`.

**Tenant table:**
- [x] `usage_events`: `step`, `company_id` (no foreign key), `created_at`. Unique on (workspace, step, company) for every step except `rewrite`. The app role has INSERT and SELECT only.

**Platform tables:**
- [x] `platform_settings`: one row of JSON, validated by Pydantic. It holds:
  - the plan catalog (step limits, seats, mailboxes, active campaigns, maximum leads per run, maximum per-prospect budget, features, period);
  - the default plan;
  - the kill switch (runs, drafts);
  - sign-up mode;
  - platform caps per vendor;
  - vendor pauses;
  - the finder chain, verifier and resolver;
  - LLM settings (base URL, model, writer model, prices, max tokens, temperature);
  - `superadmin_enabled`;
  - the announcement banner.
- [ ] `platform_credentials`: `vendor`, `key_version`, `nonce`, `ciphertext`, `version`, `active`, `created_by`, `created_at`, `retired_at`.

**Lead waiting:**
- [x] `companies.credit_wait_step` (nullable; a `CHECK` on the step names).

**Also (done):** [../SCHEMA.md](../SCHEMA.md), and the enums with their `CHECK`s.

### 6d.2 Entitlements and charging

- [x] **`domain/entitlements.py`:** the plan model, the Free plan's defaults, and the pure functions above.
  - Free plan: 5 discovery and 5 manual a month, other steps unlimited, 3 seats, 1 mailbox, 2 active campaigns, 30 days of access.
- [x] **Charging** in `Runner._apply`, `IntakeService` and `ReviewService`. A unique-key conflict means "already charged" and is not an error.
- [x] **The guard** checks credits before a step that charges, and the access level before any work.
- [ ] **Limits on create:**
  - seats at invite (pending invites count);
  - mailboxes at connect;
  - campaigns at create;
  - the maximum per-prospect budget at settings save. Today a blank field means "no limit" (`Settings.tsx`), which a platform-paid customer must not be able to choose.
- [ ] **Vendor spend:**
  - each customer's monthly vendor cap is checked in `check_budget` (`metering/budget.py:39-58`);
  - the platform's monthly cap per vendor is checked by a tick job, which sums spend across workspaces as the platform role, pauses the vendor and alerts admins. Vendors' prepaid balances are the backstop.

### 6d.3 Waiting and resuming

- [x] The guard's refusal with "wait for credits"; `credit_wait_step`; one event; `due()` skips waiting leads.
- [x] Waiting import rows, and discovery capped at the credits left.
- [x] The automatic resume job, oldest first and capped by the credits available.
- [x] Customer endpoints:
  - `POST /api/companies/{id}/resume`;
  - `POST /api/companies/resume`;
  - `POST /api/targets/resume`;
  - `GET /api/usage`: meters, grants, `access_until`, waiting counts;
  - `POST /api/usage/request-credits`: step and note. It notifies platform admins, and the request shows on the admin Overview until a grant or a dismissal.

### 6d.4 Vendor keys and model settings in the database

- [ ] **`platform_credentials`** is encrypted with `db/crypto.py`. The previous version of each key is kept for 30 days for a one-click rollback.
- [ ] **`VendorConfig`:** keys, chain, prices, caps, pauses and LLM settings, built from `platform_credentials` and `platform_settings`. In development and tests it is merged over the `Settings` defaults.
  - `real_providers` (`pipeline.py:96-119`) takes a `VendorConfig`.
  - The config carries a version stamp. It is checked when each run is assembled, and every 30 seconds in the API; a change rebuilds the adapters **without a restart**.
- [ ] **`outbound vendors import-env`** copies today's keys and model settings in once. After that, production reads them only from the database, and Doppler keeps only infrastructure secrets: database URLs, `SESSION_SECRET`, `SECRETS_KEYS`.
- [ ] **Test a key:** the vendor's free account or credits endpoint where one exists. Otherwise one minimal call, metered to the platform's internal workspace.
- [ ] **Reveal** returns the full key once and writes an audit row. Keys never reach logs or ordinary responses: they are always masked as `••••last4`.

### 6d.5 Admin API (`api/routers/admin.py`, `services/admin.py`)

All routes are under `/api/admin/*`, for platform `admin` or `superadmin`. Every write creates an `audit_log` row with before, after and the optional note.

- **Overview:** `GET /overview` (figures, needs attention, credit requests, recent activity).
- **Customers:**
  - `GET /customers` (filters and search); `POST /customers` (from 6b); `GET /customers/{id}`;
  - `PATCH …/plan`; `POST …/access` (extend); `PATCH …/status` (active, paused, suspended, with a note);
  - `PUT` and `DELETE …/overrides/{key}`;
  - `POST …/grants` (step, amount, expiry, note, resume now); `DELETE …/grants/{gid}`;
  - `POST …/resume`;
  - members: role, remove, resend invite, send reset, sign out everywhere;
  - mailboxes: force reconnect, disconnect;
  - `GET …/activity`.
- **Users:** list and search; disable or enable; send reset; sign out everywhere; set the platform role (superadmin only).
- **Plans:** `GET` and `PUT /plans` (the catalog); the default plan.
- **Vendors:**
  - `GET /vendors`;
  - `POST /vendors/{v}/reveal`; `PUT /vendors/{v}/key`; `POST /vendors/{v}/test`; `POST /vendors/{v}/rollback`;
  - `PATCH /vendors/{v}` (paused, price, cap);
  - `PATCH /vendors/chain`; `PATCH /llm`.
- **Settings:** `GET` and `PATCH /settings`.
- **Audit:** `GET /audit` (filters; CSV).


*Built (2026-10-24):* the routes above except members (role, remove, resend, force-reconnect) and the vendor routes (6d.4, next). Credit requests are `credits_requested` audit rows, open until a `credits_granted` or `credits_dismissed` row for the same customer. Every change writes its audit row in the same transaction.

### 6d.6 Admin console UI (`web2`, `/admin`)

> **As built:** Overview, Customers, Customer detail, Users, Plans, Settings and Audit log are built (`web2/src/admin/`). Vendors & keys and Directory wait for 6d.4 and 6g. Browser tests: `web2/e2e/admin.spec.ts`.

#### Principles

- **A separate shell at `/admin`,** reached from the user menu, with an amber strip labelled **ADMIN · ALPHA**, so an admin never mistakes it for a customer's workspace. **Back to app** is always visible.
- **Built from web2's tokens and parts:** `Card`, `Table`, `Tabs`, `Dialog`, `Confirm`, `QueryState`, and the drawer and toast from 6c.
- **Desktop-first:** dense 40px rows. It works on a tablet; on a phone, cards replace tables.
- **Global search** (Ctrl/Cmd+K) across customers, users, domains and email addresses.
- **Every change:**
  - is confirmed in a dialog that states its effect ("2 waiting leads will resume");
  - takes an optional note;
  - ends with a toast showing the server's result;
  - appears in the audit log.

  Admin writes are never optimistic.
- **Limits always show** used, limit, grants, remaining and the reset date. Dates are shown in the admin's time zone, with UTC on hover.
- **Empty, loading and error states** use `Empty`, `Skeleton` and `Problem`. An error never clears a form.

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│▌ OUTBOUND  ADMIN · ALPHA      Search customers, users, domains…  (Ctrl K)          │
│                                                     Rahul · superadmin ▾   App ↗  │
├────────────────┬──────────────────────────────────────────────────────────────────┤
│ Overview       │                                                                  │
│ Customers      │                       (page)                                     │
│ Users          │                                                                  │
│ Plans          │                                                                  │
│ Vendors & keys │                                                                  │
│ Directory      │   (6g)                                                           │
│ Settings       │                                                                  │
│ Audit log      │                                                                  │
└────────────────┴──────────────────────────────────────────────────────────────────┘
```

#### 1. Overview: what needs a decision today

```
Overview                                                           This month ▾
┌─────────────┬─────────────┬─────────────┬──────────────┬──────────────┬─────────────┐
│ Customers   │ Leads added │ Drafts made │ Vendor spend │ Directory    │ Waiting for │
│ 12 active   │ 418         │ 211         │ $86 of $300  │ 31% hits     │ credits     │
│ 2 expire <7d│ ▲12% vs Oct │             │ platform cap │ $29 saved    │ 23 · 4 cust.│
└─────────────┴─────────────┴─────────────┴──────────────┴──────────────┴─────────────┘
Needs attention                                    Spend by vendor, 30 days
 ● Hunter key failing (401) since 09:12  [Fix key]  ████████ DeepInfra  $41
 ● Globex asked for more credits         [Grant]    █████    Tavily     $24
 ● Acme: mailbox needs reconnect         [Open]     ███      ZeroBounce $14
 ● Run 7f2… no heartbeat for 31 min      [Open]
Recent admin activity: Rahul granted +10 manual leads to Acme · 12 min ago …
```

#### 2. Customers

```
Customers   [Search name, domain, email]  Plan [All ▾]  Access [All ▾]
            ☐ Near a limit  ☐ Waiting for credits  ☐ Mailbox problem          [+ Invite customer]
┌─────────────────────┬────────┬────────────────┬───────────────────────┬─────────┬────────┬──────────┬──────────┐
│ Customer            │ Plan   │ Access         │ Leads this month      │ Spend   │ Mailbx │ Dir. skip│ Active   │
├─────────────────────┼────────┼────────────────┼───────────────────────┼─────────┼────────┼──────────┼──────────┤
│ Acme Energy         │ Free   │ ● until 30 Nov │ Disc ▰▰▰▱▱ 3/5        │ $3.10   │ 1 ✓    │ off      │ 2 h ago  │
│ acme-energy         │        │                │ Man  ▰▰▰▰▰ 5/5 · 2 ⏸  │         │        │          │          │
│ Globex Ltd          │ Custom │ ○ expired 1 Nov│ Disc 9/15 · Man 20/20 │ $11.40  │ 2 ⚠    │ allowed  │ 3 d ago  │
└─────────────────────┴────────┴────────────────┴───────────────────────┴─────────┴────────┴──────────┴──────────┘
```

- Columns sort, and ⏸ counts waiting leads.
- A row opens the customer.
- **Invite customer** asks for the company name, website, the first admin's email and the plan. It creates the workspace and sends the invite.

#### 3. Customer detail

```
← Customers
Acme Energy · acme-energy · [Free] · ● Active until 30 Nov 2026 · 3 members · 1 mailbox · since 2 Oct
                                        [Grant credits] [Extend access] [Open workspace ↗] [More ▾]
                                        More: Change plan · Pause engine · Suspend · Delete workspace
Overview | Limits & credits | Access & features | Members | Mailboxes | Activity
```

**Overview tab:**
- step meters for this period;
- spend by vendor;
- a small funnel of leads by status;
- waiting work, with **Resume all now** when credits exist;
- open requests for credits.

**Limits & credits tab:**

```
Period 1–30 Nov · resets in 8 days                                     [Grant credits]
┌──────────────────┬──────┬──────────┬────────┬──────┬───────────────┬─────────┐
│ Step             │ Plan │ Override │ Grants │ Used │ Remaining     │         │
├──────────────────┼──────┼──────────┼────────┼──────┼───────────────┼─────────┤
│ Discovery leads  │ 5    │ —        │ +10    │ 9    │ 6             │ Edit ▸  │
│ Manual leads     │ 5    │ 20       │ —      │ 20   │ 0 · 2 waiting │ Edit ▸  │
│ Research         │ ∞    │ —        │ —      │ 29   │ ∞             │ Edit ▸  │
│ Email finding    │ ∞    │ —        │ —      │ 27   │ ∞             │ Edit ▸  │
│ Writing          │ ∞    │ —        │ —      │ 24   │ ∞             │ Edit ▸  │
│ Drafts to mailbox│ ∞    │ —        │ —      │ 19   │ ∞             │ Edit ▸  │
│ Rewrites         │ ∞    │ 50       │ —      │ 12   │ 38            │ Edit ▸  │
└──────────────────┴──────┴──────────┴────────┴──────┴───────────────┴─────────┘
History  +10 discovery · Rahul · 12 Nov · "pilot extension" · expires 30 Nov   [Revoke]
         Manual limit 5 → 20 · Rahul · 2 Nov · no expiry                         [Undo]
```

- **Edit ▸** opens a drawer. It sets an override (a number or unlimited), with an optional expiry and note, and shows "remaining after" live.
- **Grant credits:**

```
┌ Grant credits · Acme Energy ─────────────────────────────────┐
│ Step      [Manual leads ▾]      Amount [ 10 ]                 │
│ Expires   (•) End of this period  ( ) On [date]  ( ) Never    │
│ Note      [Pilot extension                                 ]  │
│ ☑ Resume the 2 waiting leads now                              │
│ Remaining after: 10 manual leads                              │
│                                   [Cancel]  [Grant 10 credits]│
└───────────────────────────────────────────────────────────────┘
```

- **Extend access:** +7 days, +30 days, or a date. It shows the new "active until", and a read-only workspace reopens at once.

**Access & features tab:**
- the plan selector, which shows what changes before saving;
- status (active, engine paused, suspended), with a note;
- feature toggles: **Can skip the lead directory** (6g), discovery, and later follow-ups and automatic sending;
- maximum per-prospect budget, seats, mailboxes, active campaigns.

**Members tab:** name, email, role, last sign-in. Invite, change role, remove, resend invite, send password reset, sign out everywhere.

**Mailboxes tab:** address, type, status, last check, DNS results. Force reconnect, disconnect.

**Activity tab:** admin actions for this customer, and key events (runs, failures, credit stops).

**Open workspace ↗** (superadmin only) opens `/w/{slug}` read-only, behind the red banner from 6b.

#### 4. Users

- Every user, with their workspaces and roles, platform role, last sign-in and status.
- Actions: send password reset; disable or enable; sign out everywhere; set the platform role (superadmin only).

#### 5. Plans

- The catalog, with Free as the default.
- Edit step limits, seats, mailboxes, active campaigns, features and the period. Saving says "applies to 9 customers".
- Choose the default plan for new customers.

#### 6. Vendors & keys

```
Vendors & API keys                     Finder chain [Hunter ⇅] [ZeroBounce ⇅]   Verifier [OrbiSearch ▾]   Resolver [Scrubby ▾]
┌────────────────┬──────────────────┬──────────────────┬─────────────┬──────────────┬──────────────────┬──────────────────────┐
│ Vendor         │ Key              │ Status           │ Spend / cap │ Price        │ Last 24 h        │                      │
├────────────────┼──────────────────┼──────────────────┼─────────────┼──────────────┼──────────────────┼──────────────────────┤
│ DeepInfra (LLM)│ ••••••••9f2c [👁] │ ● OK             │ $41 / $150  │ in/out per 1M│ 1,204 · 0.4% err │ Test · Replace · ⏸   │
│ Tavily         │ ••••••••a1b0 [👁] │ ● OK             │ $24 / $60   │ $0.008/credit│ 310 · 0%         │ Test · Replace · ⏸   │
│ Hunter         │ ••••••••77de [👁] │ ● 401 since 09:12│ $9 / $49    │ plan         │ 44 · 100% err    │ Test · Replace · ⏸   │
│ Companies House│ not set          │ ○ off            │ —           │ free         │ —                │ Add key              │
└────────────────┴──────────────────┴──────────────────┴─────────────┴──────────────┴──────────────────┴──────────────────────┘
LLM   Base URL [https://api.deepinfra.com/v1/openai]  Model [deepseek-ai/…]  Writer model [ … ]
      Price per 1M tokens in [ ] out [ ]   Max tokens [ ]   Temperature [ ]                       [Send test prompt]
```

- **[👁] Reveal** shows the whole key for 30 seconds and is audited.
- **Replace:**
  1. paste the new key;
  2. **Test**;
  3. **Save**.

  The new version becomes active, and the previous one stays available for **Rollback**.
- **⏸ Pause:** the chain skips a paused vendor, and work that needs it waits.
- **Effect:** changes apply without a restart (6d.4).

#### 7. Directory

Built in 6g: data quality, reports, reconfirmation, hit rate and savings.

#### 8. Settings

- the global kill switch (runs, drafts), with a typed confirmation;
- sign-up mode (invite-only in the alpha);
- the platform's monthly caps per vendor;
- the superadmin switch;
- an announcement banner shown in every workspace.

#### 9. Audit log

- every admin and superadmin action, including key reveals and workspace views;
- filters by actor, customer, action and date;
- CSV export.

### 6d.7 Customer-side screens

- [x] **Settings → Plan & usage:**
  - a meter per step (used, limit, grants, reset date);
  - "active until";
  - the list of grants;
  - **Ask for more credits**.
- [x] **Banners:**
  - 80% and 100% of a step;
  - access ending within 7 days, or ended (read-only);
  - engine paused or workspace suspended;
  - admin announcements.
- [x] **Waiting for credits:**
  - a filter and count on Needs attention;
  - waiting rows on Add leads;
  - **Resume** and **Resume all**.
- [ ] The tour, [../USER_MANUAL.md](../USER_MANUAL.md) and `screens.spec.ts` are updated. The admin console gets its own tour section, shown only to platform roles.

### 6d.8 Notices (`TransactionalEmail`)

- [ ] **To workspace admins:**
  - a step at 80% and at 100%;
  - access ends in 7 days, and access ended;
  - credits granted.
- [ ] **To platform admins:**
  - a credit request;
  - a vendor key failing;
  - a vendor paused by its cap.

## Tests that must exist

- **Domain:**
  - `effective_entitlements` with overrides and expiry;
  - `available` with grants (end of period, dated, never);
  - the period anchor;
  - `access_level` for every combination.
- **Charging:**
  - once per lead and step, across retries, research again, reruns and a deleted lead;
  - `rewrite` repeats;
  - a merge charges nothing;
  - discovery is capped at the credits left.
- **Waiting and resuming:**
  - a lead waits in place;
  - automatic resume is oldest first and never exceeds the credits;
  - Resume without credits is refused with the reset date;
  - an approved email survives a wait at `deliver`.
- **Vendor config:**
  - a key is replaced and the next call uses it with no restart;
  - rollback;
  - reveal is audited;
  - keys are never in logs or ordinary responses.
- **Admin:**
  - every endpoint's permission (admin versus superadmin);
  - every write is audited;
  - a suspended customer gets no claims;
  - the platform cap pauses a vendor.
- **Playwright:**
  - a free customer's 6th manual lead waits, the admin grants with "resume now", and the lead runs;
  - the admin replaces a key;
  - extending access reopens a read-only workspace;
  - the superadmin opens a workspace read-only.

## Gate record

- Date:
- Free-plan limits and resume demo:
- Key replacement without restart:
- Alpha pilots (customers, month, spend against invoices):
- Checked by:
