# Phase 7 — Later: the backlog

**Goal:** one place for everything that was deliberately left out, so nothing is lost and nothing is built early.

**Status (2026-10-23):** a holding list, not a scheduled phase.

**Already scheduled after the alpha, so not repeated here:**
- [6e Billing](phase-6e-billing.md): payments, trials, open sign-up.
- [6f Launch readiness](phase-6f-launch-readiness.md): MFA, a support role replacing superadmin, Google CASA, the directory's legal steps, penetration test, staging, backups drill.
- [Phase 5 Automated sending](phase-5-automated-sending.md).

**How an item leaves this list:**
- Only when a **measured need** appears: a customer asks for it, a deal depends on it, or a number shows it (cost, latency, volume).
- It then gets its own phase document, or joins an existing one, with tasks, files and a gate.
- If it changes behaviour, [../PLAN.md](../PLAN.md) changes in the same PR.
- Items marked *non-goal* need a team decision first, because PLAN.md rules them out today.

**Gate:** none. Each item gets one when it is scheduled.

## Customers and accounts

| Item | Why it waits | Pull it in when | Notes |
|---|---|---|---|
| Agency accounts | Alpha customers are single companies | Agencies sign up and need several client workspaces under one login and one bill | An account table above `workspaces` plus a nullable key on `workspaces`: additive, nothing reshaped |
| Client-only users (per-campaign or per-client access) | No per-record sharing is needed yet | An agency's client must see only their own campaign | First option: a `campaign_members` table checked by `can(…, resource)`. A relationship engine (OpenFGA, Cedar) only if rules multiply |
| Custom roles | Fixed admin/member roles cover the alpha | A customer needs a role between admin and member | A `roles` table mapping to the existing permission strings; call sites unchanged (6b) |
| Owner and viewer roles | Admin and member suffice | Customers ask for billing-only owners or read-only viewers | Listed as optional in 6f |
| Workspace audit log for customers | Only platform admins read the audit log in the alpha | Customers ask who changed what | Read `audit_log` rows for the workspace; no new table |
| Self-service email change | A platform admin changes emails in the alpha | Requests become routine | Verify the new address with a single-use link |
| "Require MFA for everyone" per workspace | MFA itself arrives in 6f | A customer's security policy demands it | A workspace setting checked at sign-in |

## Identity

| Item | Why it waits | Pull it in when | Notes |
|---|---|---|---|
| SSO (SAML or OIDC) | No enterprise customers in the alpha | A deal requires it | Supabase Auth (Pro) or WorkOS behind the existing `IdentityProvider` port (6b) |
| SCIM user provisioning | Same | A customer's IT team requires it | WorkOS is the shortest path; Supabase Auth has no SCIM |
| Passkeys | Passwords meet the alpha's needs | After MFA (6f), as the next sign-in upgrade | Comes with a managed identity provider |

## Mailboxes and sending

| Item | Why it waits | Pull it in when | Notes |
|---|---|---|---|
| Inbox rotation across several mailboxes | Volume fits one mailbox's daily cap (Phase 5, Out) | A customer's volume passes one mailbox's cap | Campaign picks a set of mailboxes; the send scheduler spreads by cap |
| Push instead of polling for replies | Polling is enough at alpha volume | Polling cost or reply latency becomes a problem | Gmail `users.watch` with Pub/Sub; Microsoft Graph change notifications |
| EmailEngine as a gateway | Direct adapters are simpler (PLAN decision 10) | Holding many IMAP connections becomes a burden | It needs Redis, an exception to the no-queue rule; behind the same `Mailbox` port |
| SMTP for non-IMAP providers | Not needed for drafts | A customer's provider offers SMTP but not IMAP | Part of the IMAP adapter's SMTP side (Phase 5) |
| Warm-up network | PLAN §11 ramps daily caps instead | Not planned | Shared warm-up pools carry deliverability and abuse risk |

## Lead directory

| Item | Why it waits | Pull it in when | Notes |
|---|---|---|---|
| Research seeds people from the directory | 6g starts with emails and patterns | Directory coverage is high enough to save searches | Saves Tavily searches in persona discovery (6g, "Later") |
| Source filters | All facts are shareable in the alpha | Counsel or a vendor's terms require it (6f) | Every fact already keeps its source |
| Directory search for customers | The directory serves the engine only | Legal sign-off is done and customers ask to browse it | A product decision: makes the platform a data seller, with the obligations in 6f |
| Company-level enrichment beyond today's fields | Not needed for the waterfall | A customer workflow needs firmographics | Size, industry codes, funding; only from shareable sources |

## Integrations

| Item | Why it waits | Pull it in when | Notes |
|---|---|---|---|
| Public API with workspace API keys | The web app is the only client | Customers want to automate | Hashed keys scoped to one workspace, a permission set each, rate limits |
| More outbound webhooks | Intake and positive-reply webhooks cover the alpha | Customers ask for events (lead status, reply, bounce) | Signed like the intake webhook; per workspace |
| CRM sync (HubSpot, Salesforce, Pipedrive) | *Non-goal* in PLAN §2: positive replies go out by webhook or export | The team changes the non-goal | Needs PLAN.md changed first |

## Billing extras (after 6e)

| Item | Why it waits | Pull it in when | Notes |
|---|---|---|---|
| Usage-based overage | Plans with fixed credits come first | Customers hit limits often and prefer to pay as they go | `usage_events` already gives Stripe meter events an idempotency key |
| Annual plans and discounts | Monthly first | Sales asks for them | Stripe prices only |
| Consolidated billing for agencies | Agency accounts come first | Agency accounts exist | One customer in Stripe per account |

## Platform and operations

| Item | Why it waits | Pull it in when | Notes |
|---|---|---|---|
| Regional hosting (an EU data region) | One region at launch | A customer requires EU residency | A second Supabase project and deployment; workspace records its region |
| Horizontal scaling | One API and one worker container are enough | Load tests (6f) or real load show limits | More worker containers (claims already use `SKIP LOCKED`), a bigger Supabase compute tier, read replica for reports |
| In-app notification centre | Banners and emails cover the alpha | Notices get missed | A small table per user; banners stay |
| Background data export | Exports stream directly | A workspace is too large to export in one request | A run of kind `export` and an expiring download |
| SOC 2 | Not needed for the alpha | Enterprise buyers ask for it | Builds on 6f's controls and the audit log |
| White-label | No partner demand | A partner wants their own brand | Brand settings per workspace or account |
| Marketing site and pricing page | Outside the app | Before open sign-up (6e) | Separate project |

## Engineering debt carried from 3b

| Item | Notes |
|---|---|
| Long functions | Split when the code is next touched |
| Magic numbers into settings | Back-off, retry limits, caps that are still constants |
| Typed models for JSON columns | Pydantic models for `research`, `settings`, `sender_profile` and others |

## Not planned (non-goals in PLAN.md)

Other channels than email; LinkedIn scraping; open or click tracking. They stay out unless the team changes [../PLAN.md](../PLAN.md) §2.
