# web3 feature map

Every feature the product has today (web2 screens, the workspace API, the admin console) and
where it lives in web3. Built from `web3/openapi.json` (all `/api/*` paths), `web2/src/router.tsx`,
`web2/src/app/nav.ts`, `web2/src/pages/settingsTabs.ts`, `web2/src/tour/steps.ts` and
`web2/src/admin/`. A row without a web3 home is a gap; there are none — keep it that way when
adding a route.

## Information architecture

```
Public (no sidebar)        Sign in · Forgot / reset password · Invitation accept · OAuth return
                           · Remove my data · Workspace picker / create · Join request
Onboarding (no sidebar)    /w/{slug}/onboarding — 5 steps + "what Outbound does for you" panel
Workspace app  /w/{slug}
  Work        Today · Emails ready (badge) · LinkedIn ready (badge) · Needs a decision (badge)
  Leads       Leads · Add leads · Discovery runs · Campaigns
  Workspace   Reports · Policies & privacy · Settings
  Everywhere  ⌘K command palette · notifications bell · credits meter · theme (light/dark/system)
              · account menu (tour, account, sign out) · workspace switcher · campaign gate
Admin console  /admin — Overview · Customers · Users · Plans · Settings · Vendors & keys
               · Lead directory · Audit log
```

## Workspace features → web3 home

| Feature | API | web3 home |
|---|---|---|
| Sign in / out, sign out other sessions | `auth/login`, `logout`, `logout-others` | Public · Account menu · Settings → Account |
| Forgot / reset / change password | `auth/password/*` | Public · Settings → Account |
| Delete my account | `auth/account/delete` | Settings → Account (danger zone) |
| Accept invitation (new or existing user) | `auth/invitations/{token}*` | Public: Invitation |
| Public "remove my data" | `auth/remove-my-data*` | Public: Remove my data |
| Who am I, workspaces, roles | `auth/me` | Shell (switcher, role-aware nav, read-only banner for superadmin) |
| Create workspace, join requests | `me/workspaces`, `me/join-requests` | Workspace picker |
| Notifications + mark read | `me/notifications*` | Bell drawer (grouped by run/lead, deep links) |
| Setup checklist | `setup` | Onboarding stepper · Today "finish setup" card · Settings → Setup |
| AI profile draft from website | `setup/profile-draft` | Onboarding step 1 |
| AI campaign draft | `setup/campaign-draft` | Onboarding step 3 · Campaigns |
| Engine status / worker heartbeat | `status` | Today engine strip · shell status dot |
| Pipeline counts | `status`, `companies` | Today pipeline flow (each stage links to filtered Leads) |
| Review queue, show one | `review`, `review/{id}` | Review (3-pane, keyboard J/K/A/E/R) |
| Approve / reject / revise / AI rewrite | `review/{id}/approve|reject|revise|rewrite` | Review action bar + editor with diff |
| Needs a decision: holds, stopped steps, websites, with fit, tries, person and credits per row | `companies` (`bucket=decision`, `include=summary`), `targets/waiting` | Needs a decision (tabs by reason, filters and sort, row details, bulk bar) |
| Retry one / many failed (by step) | `companies/{id}/retry`, `companies/retry` | Needs attention · Lead detail |
| Release one / many holds, policy holds | `release-hold`, `release-holds`, `release-policy-holds` | Needs attention · Policies |
| Find email again (one / all catch-all) | `companies/find-email-again`, `contacts/{id}/retry-email` | Needs attention · Lead detail |
| Resume leads waiting for credits | `companies/resume`, `companies/{id}/resume`, `targets/resume` | Needs attention · credits meter popover |
| Confirm website for uploaded rows | `targets/{row_id}/confirm` | Needs attention → Websites · Add leads |
| Leads list with filters in URL | `companies` | Leads (saved views, filter pills, fit pill, status chip) |
| Sort leads by any column, either way | `companies?sort&direction` | Leads (Sort menu, direction arrow, column titles) |
| Lead website icons | DuckDuckGo icon service (CSP `img-src`) | Leads (`ui/lead.tsx::LeadIcon`, initials if none) |
| Set or remove a person's LinkedIn profile | `PATCH contacts/{id}` (`linkedin_url`) | Lead page: person **Remove**, **Edit** field |
| Find people again | `POST companies/{id}/find-people` | Lead page, under People when nobody can be written to |
| Lead detail: status, next actions, edit fields | `companies/{id}` GET/PATCH | Lead detail header + inline edit (manual fields marked) |
| Research again / requalify | `research-again`, `requalify` | Lead detail actions |
| Qualification breakdown | `companies/{id}` | Lead detail "Why this lead" card |
| People: add, confirm, not here, remove, edit | `people`, `contacts/{id}*` | Lead detail People card |
| Change recipient, check people | `change-recipient`, `check-people` | Lead detail People card |
| Consent record per contact | `contacts/{id}/consents` | Lead detail People card |
| Suppress contact / company, delete lead | `contacts/{id}/suppress`, `companies/{id}/suppress|delete` | Lead detail danger menu |
| Skip / restore email verification | `contact-emails/{id}/skip-verification` | Lead detail email row |
| Email waterfall (which vendor found/verified) | `companies/{id}/waterfall` | Lead detail "How we found the address" stepper |
| Shared directory badge, report, skip | `companies/{id}/directory*` | Lead detail Directory card |
| Country policy skip / revoke | `companies/{id}/policy-skip` | Lead detail Country rule card |
| Timeline / Activity (vendor call detail) | `companies/{id}/timeline` | Lead detail Activity tab |
| Journey (8 stages, how it arrived) | `companies/{id}/journey` | Lead detail Journey tab (was separate page) |
| LinkedIn lookup per person | `contacts/{id}/find-linkedin` | Lead detail People card |
| LinkedIn drafts: write, edit, sent, skip, restore | `contacts/{id}/linkedin`, `linkedin*`, `companies/{id}/linkedin` | LinkedIn ready page (filters, sort, folding rows; Today's sideways strip) · Lead detail |
| Add one company | `targets` | Add leads → Single |
| Upload a list | `targets/upload` | Add leads → Upload (drag-drop, column mapping preview) |
| Intake webhook info / rotate secret | `integrations/webhook*` | Add leads → Webhook · Settings → Integrations |
| Runs list, start run, cancel | `runs` GET/POST, `runs/{id}/cancel` | Discovery runs (live-run card with steps; *While it runs* shows `runs/auto-discovery` `waiting_for_review`) |
| Auto-discovery state (paused at 50 drafts) | `runs/auto-discovery` | Discovery runs header · Today engine strip |
| Run detail: leads, calls, searches, candidates | `runs/{id}/*` | Run detail tabs |
| Promote candidate ("Make a lead") | `candidates/{id}/promote` | Run detail Candidates tab |
| Campaigns: list, create, edit, activate, pause | `settings/campaigns*` | Campaigns (one active, gate when none) |
| ICP brief + regenerate | `settings/campaigns/{id}/brief/regenerate` | Campaigns "Who we look for" |
| Reports: funnel, cost, quality, sources | `reports/*` | Reports (charts, date range) |
| Country policies on/off | `settings/policies*` | Policies & privacy |
| Suppression list | `settings/suppressions` | Policies & privacy |
| Forget a person (GDPR) | `privacy/forget` | Policies & privacy |
| Sender profile + JSON template download | `settings/sender-profile*` | Settings → Profile · Onboarding 1–2 |
| Workspace settings (limits, auto-approve cold) | `settings/workspace` | Settings → Limits |
| Mailboxes: list, OAuth, IMAP, test, pause, resume, sender, default, disconnect, options | `mailboxes*` | Settings → Mailboxes · Onboarding 5 |
| DNS check (SPF/DKIM/DMARC) | `settings/mailboxes/{id}/dns-check` | Settings → Mailboxes · Onboarding 5 |
| Plan, usage, request credits | `usage`, `usage/request-credits` | Settings → Plan · credits meter |
| Team: members, roles, invites, join code, join requests | `team*` | Settings → Team |
| Product tour | — | Account menu + `?` key; steps for every web3 screen |

## Admin console → web3 home

Overview; Customers (plan, access, status, overrides, grants, resume, dismiss request, members,
mailbox reconnect); Users (disable/enable, sign out, delete, platform role); Plans (default,
edit, credit rate; superadmins only); Settings; Vendors & keys (up to three keys, test, reveal,
rollback, pause, cap in AI credits, LLM settings and model charges in AI credits); Lead directory (flags, history, entries, companies); Audit log + CSV; Invitations.
web3 keeps the same eight pages under `/admin`, in the same visual system, with a distinct
header colour so staff always know they are in the console.
