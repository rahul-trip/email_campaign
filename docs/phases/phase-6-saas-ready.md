# Phase 6 — SaaS (alpha track)

**Goal:** invited companies use one deployment safely. Each company:
- works in its own workspace, with its own team, mailboxes and limits;
- shares none of its own data with any other customer.

Platform admins run every customer from an admin console. A shared directory of verified business facts cuts vendor cost.

**Status (2026-10-23):** planned and approved. This document replaced the earlier one-page Phase 6 and is now an overview. The work is in seven sub-phases, 6a–6g.

**Depends on:** Phase 3b, including its prerequisites for 6a (see [phase-3b-hardening.md](phase-3b-hardening.md), §8).

**Gate (the whole track):** a second workspace, seeded with its own leads, runs the full pipeline. Automated tests then confirm that no API call, query or export from workspace A returns any row from workspace B. The same must hold when application-level scoping is deliberately bypassed, because row-level security still blocks access. Each sub-phase also has its own gate.

## Decisions (2026-10-22 and 2026-10-23)

| # | Decision | Choice |
|---|---|---|
| 1 | Customer shape | One company = one workspace. A user may belong to several workspaces |
| 2 | Release | An invite-only **alpha**. No payments, and no MFA, social sign-in or SSO |
| 3 | Isolation | Shared database and schema; `workspace_id` on every tenant row; composite foreign keys; Postgres row-level security under a least-privilege app role |
| 4 | Sign-in | Email and password (Argon2id) with invitations, password reset and server-side sessions, behind an `IdentityProvider` port so a managed provider can replace it later |
| 5 | Workspace roles | `admin` and `member`. A workspace always keeps one admin |
| 6 | Platform roles | `admin` (the console, no lead content) and `superadmin` (alpha only: reads every workspace) |
| 7 | Vendor costs | The platform owns the vendor keys. Admins see and update them in the console. Keys are stored encrypted in the database |
| 8 | Limits | Credits per pipeline step, charged once per lead. The free plan allows 5 discovered + 5 manually added leads a month. Admins set any limit, grant credits and extend access time |
| 9 | Stops | Every lead can be resumed. A lead stopped by a limit waits in place and resumes once credits exist |
| 10 | Mailboxes | Connected in Settings only: Microsoft 365 (Graph, OAuth), Google (Gmail API, OAuth) or any IMAP account (app password) |
| 11 | LLM | DeepSeek served by DeepInfra (OpenAI-compatible), replacing OpenRouter |
| 12 | Lead directory | Shared verified facts (companies, people, LinkedIn profiles, emails), checked before any paid vendor. All facts are shareable. Customers may skip the directory when an admin allows it |

## The sub-phases

| Sub-phase | Document | Delivers | Depends on |
|---|---|---|---|
| 6a | [Tenancy foundation](phase-6a-tenancy-foundation.md) | Scoping gaps closed, composite FKs, row-level security and roles, platform unit of work, services per request, the multi-tenant worker | 3b |
| 6b | [Identity and access](phase-6b-identity-and-access.md) | Users, invitations, password reset, sessions, roles and permissions, superadmin, `/w/{slug}` URLs, Team page | 6a |
| 6c | [Onboarding and mailboxes](phase-6c-onboarding-and-mailboxes.md) | Encrypted credentials, the IMAP, Graph and Gmail adapters, per-mailbox delivery, sender identity, onboarding wizard, Settings layout | 6b |
| 6d | [Plans, limits and admin](phase-6d-plans-limits-and-admin.md) | Plans, per-step credits, grants and access time, waiting and resuming, vendor keys in the database, the admin console | 6c |
| 6g | [Verified lead directory](phase-6g-lead-directory.md) | Shared verified facts, the free first link of the email waterfall, reports and reconfirmation, the skip option | 6d |
| 6e | [Billing](phase-6e-billing.md) | **After the alpha:** payments and trials | 6d |
| 6f | [Launch readiness](phase-6f-launch-readiness.md) | **After the alpha:** MFA, a support role in place of superadmin, Google CASA, legal steps for the directory, penetration test | 6e |

## Order

```
NOW  Close the Supabase Data API (phase-3b-hardening.md, E8)
3b   Finish, including B2 B3 B4 B5 B7 (migration 0006)
6a   Tenancy foundation
6b   Identity and access
6c   Onboarding, Settings and mailboxes    ← apply for Google and Microsoft app verification here
6d   Plans, limits, credits, admin console
4a   Opt-out and hard-bounce handling (from Phase 4)
     → ALPHA (invite-only)
6g   Verified lead directory   } in parallel; the alpha
4    Rest of Phase 4           } waits for neither
──── after the alpha ────
6e   Billing          6f   Launch readiness          5   Automated sending
```

## How customers are kept apart

1. **Application scoping.** Every repository is bound to one workspace (`UnitOfWorkFactory(workspace_id)`).
2. **Composite foreign keys.** The database refuses a link from one workspace's row to another's. Foreign-key checks ignore row-level security, so this is the only thing that stops such a link.
3. **Row-level security.**
   - Every tenant table enables and forces RLS.
   - The policy is `workspace_id = current_setting('app.workspace_id', true)`.
   - The setting is applied in every transaction, and a missing setting returns no rows.
4. **Least-privilege roles.**
   - The app connects as `outbound_app`, never as the table owner.
   - The admin console and the scheduler read across workspaces as `outbound_platform`, without BYPASSRLS.
   - Only the `migrate` container uses the owner.
5. **Tenant-bound secrets.** Mailbox and webhook credentials are encrypted. Their associated data names the workspace, so a copied ciphertext cannot be decrypted in another workspace.
6. **Proof.**
   - An isolation suite calls every route with the other workspace's ids.
   - The whole Postgres suite runs as `outbound_app`, with application scoping both on and patched out.
   - A catalog test checks every policy.

**Never shared between customers:** notes, campaigns, research answers, messages, consents, suppressions, style examples, prompts, logs, or the raw vendor cache.

**Shared:** only the verified lead directory (6g). It never shows who looked up or prospected whom.

**Platform tables** are reached only through their own repositories: users, sessions, plans and settings, vendor keys, the directory and the audit log.

## Not in the alpha

- Payments and trials (6e).
- MFA, social sign-in, SSO; owner and viewer roles; a support role with tenant-granted access, which also replaces superadmin (6f).
- Google's CASA assessment. The alpha stays within the 100-user cap of an unverified Google app.
- Open sign-up.
- Automatic sending (Phase 5).

## Not in this plan

These wait in [Phase 7](phase-7-later.md), each with the need that would pull it in.

- Agency accounts.
- SCIM and custom roles.
- Public API keys and CRM sync. CRM stays a non-goal in [../PLAN.md](../PLAN.md).
- White-label.
- A warm-up network.
- Regional hosting.
- The marketing site.

## Gate record

- Date:
- Isolation suite (SQLite; Postgres as `outbound_app`; scoping patched out):
- Second workspace full run:
- Checked by:
