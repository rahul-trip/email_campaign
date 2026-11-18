# Phase 6i — Outcomes first (proposal)

**Status:** built 2026-11-19 on branch `phase-6/outcomes-first` (one PR, separate commits), after the team's answers: one PR; tries are counted (3 for "nobody to write to", 5 for a broken step); pages are renamed; a draft is approvable from anywhere. See [ADR 0036](../technical/adr/0036-outcomes-are-not-failures.md). Mockup: Stitch project `538951827606035367`, screen "Outbound — Today Dashboard (Warm Attio Style)" (`screens/cee5732553df465f833834aba2056510`), design system `assets/7e894524ff6145c38495eb09a009b16a`. It shows the order built: emails ready with three previews, hot leads on LinkedIn, the week's wins, then a grey Behind the scenes and a small Decision required card. Do not copy its invented details ("Syncing continuous", "+1.4% benchmark", Google Workspace, profile photos).

## The problem

Outbound works like a funnel. Most companies are meant to drop out: they don't fit the brief, nobody suitable works there, or no address can be proven. The web app shows those drop-outs as failures, and the few successes get lost among them:

- `outbound/stages/contacts.py` ("no decision-maker was found…") and `outbound/stages/email/stage.py` ("no valid email found…") raise `StageFailure`. The lead goes to `failed`, which is also the status used for real errors such as a timeout or a bad key.
- Every `failed` lead counts toward the amber **Needs attention** badge (`web3/src/app/Shell.tsx`, `counts.attention`). The bell's `needs_attention` notice uses the same count.
- On Today, the first folding section is **Needs you**, with a red *Failed* card ("N leads stopped at a step"). It sits above the pipeline and the wins.
- A draft waiting in Review (`copy_ready`) is coloured `attention` (amber) in `web3/src/lib/status.ts`, so the best possible outcome looks like a warning.
- Run detail opens with a red *Failed* stat and callout before it shows what the run found.
- The Leads page puts *Failed* and *Disqualified* views next to *Approved* with the same visual weight.

So an operator who opens the app sees mostly red and amber, even on a good day.

## Principles

1. **Wins first, work second, exceptions last.** Every screen leads with what the operator can use now: emails to approve, hot leads to message, drafts in the mailbox.
2. **A filtered-out lead is an outcome, not a failure.** Use a neutral grey and calm words ("screened out", "no email we could prove"). Keep red for broken things the operator must fix: a disconnected mailbox, no credits, a refused key.
3. **Count only what a person can unblock.** A badge counts items where the operator's action creates value. Errors that are still retrying on their own belong to *working*, not to *needs you*.
4. **A hot lead without an email is still a lead.** Offer LinkedIn as the next step, not a dead end.
5. **Show yield, not loss.** Describe the funnel as "214 looked at → 31 reached you", not "183 failed".

## The four outcome buckets

Every lead belongs to exactly one bucket. The buckets are worked out from data the API already returns (status, hold reason, failed stage, attempts, fit score):

| Bucket | Contains | Tone | Where it shows |
|---|---|---|---|
| **Ready for you** | `copy_ready` (email to approve); a hot lead nobody could email, for LinkedIn | primary / good | Today hero, Emails ready, Hot leads |
| **Working** | `new` … `email_ready`; hold `catch_all_resolving`; waiting for credits; `failed` with technical errors and attempts left | neutral, with a "working" dot | Today "Behind the scenes", Leads |
| **Needs a decision** | holds `consent_required`, `country_unknown`, `entity_unknown`, `needs_operator`, `catch_all_unverified`, `linkedin_contacted`; websites to confirm; `failed` with technical errors and **no attempts left** | neutral, with one amber accent only when something is blocked | Needs a decision page, a small card on Today |
| **Screened out** | `disqualified`, `rejected`, `suppressed`; `failed` because no person or no provable email was found | grey | collapsed "Screened out" on Leads, Reports, Run detail |

A fifth group, **Done** (`approved`, `in_sequence`, `replied`, `completed`), is kept apart so the "emails ready" count is only what still needs approving.

The exception: a **hot** lead (fit above 80) that is screened out for want of an email moves to *Ready for you → Hot leads*, with its LinkedIn message.

## Screen by screen

### Navigation (`web3/src/app/nav.ts`, `Shell.tsx`)
- Rename and reorder the Work group: **Today · Emails ready** (was Review, same `/review` path) **· Hot leads** (was LinkedIn, same `/linkedin` path) **· Needs a decision** (was Needs attention, same `/attention` path).
- The Needs a decision badge counts only that bucket and uses the neutral badge style, not amber.

### Today (`web3/src/pages/Today.tsx`)
In order:
1. **Hero: "12 emails are ready for you"**, with the top three drafts by fit as preview cards (subject, two lines, Approve / Open). Approve uses the existing `review/{id}/approve`. If Review is empty, the hero shows what is in the mailbox ready to send, then the hot leads.
2. **Hot leads: reach them on LinkedIn.** Up to three person cards, each with its connection note and *Copy note*, *Open profile* and *Mark sent* (the existing `LinkedInDraftCard` actions), plus a link to the full page.
3. **This week:** drafts approved, in your mailbox, replies. These are the wins, with count-ups and sparklines.
4. **Behind the scenes** (collapsed, grey): the yield bar *Looked at → Fit your brief → Person found → Email ready → Reached you*, with "Screening most out is how the list stays sharp", and links to the pipeline and the screened-out list. It replaces today's *Lead pipeline* river and the red *Failed* card.
5. **Needs a decision** (small, neutral): shown only when that bucket is not empty, with chips by reason.
6. Active campaign, Sources and What happened stay, collapsed, below.

The KPI row loses *AI credits used* (it moves to the credits meter and Reports). Today shows wins only.

### Emails ready (`Review.tsx`)
- Change `copy_ready` from `attention` to `primary` in `lib/status.ts` (label "Ready to approve").
- Small celebratory touches already exist (confetti at milestones). Add a "You cleared Review" end state that points to Hot leads.

### Hot leads (`LinkedIn.tsx`)
- Default list: drafted messages for hot leads first (fit, descending), then the rest.
- Add hot leads that could not be emailed. If such a lead has no LinkedIn draft yet, it gets a *Write a LinkedIn message* button. Draft creation for a lead already exists (`companies/{id}/linkedin`).
- Group header: "Email couldn't be proven, so start on LinkedIn" for that group.

### Needs a decision (`Attention.tsx`)
- Title "Needs a decision". Subtitle: "A few leads need a choice only you can make. Everything else runs by itself."
- Remove the *Failed at people* and *Failed at the email address* groups: those leads are screened out and listed on Leads. Technical failures show only after the last attempt, under one group, "Stopped after 3 tries", with *Retry all*.
- Section tone is neutral. Error red is used only for "Stopped after 3 tries".

### Leads (`Leads.tsx`)
- Saved views: **Ready for you · Working · Needs a decision · Screened out · All**. The default is *Ready for you* when it is not empty, otherwise *All*.
- On a screened-out lead, the row says why in grey ("No email we could prove", "Not a fit: rule-out met") instead of a red `last_error`.

### Run detail (`RunDetail.tsx`)
- Lead with the outcome: "This run found 9 new leads and wrote 4 drafts". Then the step table. The candidate list moves to a collapsed "Screened out by the brief (normal)" section.
- The red callout appears only when the run itself failed.

### Bell (`Bell.tsx`, `services/activity_notices.py`)
- `needs_attention` counts only the *Needs a decision* bucket. If it is zero, there is no notice.
- `drafts_ready` and `hot_lead` stay; "N drafts ready" is the notice operators see most.

## Backend changes (small)

1. **Tell an outcome from an error.** Add `failure_kind` (`no_person` | `no_email` | `error`) to `failed` companies:
   - add a `kind` to `StageFailure`, defaulting to `error`;
   - set it in `contacts.py` and `email/stage.py`;
   - store it with `failed_stage`.

   This needs a migration (a column with a `CHECK`) and a `schema.md` update. A `no_person` or `no_email` failure is not retried automatically (it wastes credits for the same answer); *Find email again* and *Find people again* remain the manual paths. This is a behaviour change, so record it in `docs/PLAN.md`.
2. **Bucket counts in one call.** Extend `StatusOut` with `buckets: {ready, working, decision, screened_out}` and `hot_unreachable`, computed in the status repository. Shell, Today and the bell read it, so the badge logic lives in one place, server side.
3. **Filters.** `GET /api/companies?bucket=…` and `GET /api/linkedin?hot=true` back the Leads views and the Hot leads list.
4. `npm run gen:api`. Keep the parity check (`check:parity`) green. Update `FEATURE_MAP.md`.

No new tables, queues or services.

## Docs and tour
- `docs/USER_MANUAL.md`: the renamed pages, the four buckets, what "screened out" means.
- `web3/src/tour/steps.ts`: the Today step points at the "ready for you" hero, a new step covers Hot leads, and the Needs attention step is renamed.
- `docs/technical/lld/` for the runner (`failure_kind`, no retry for outcomes) and the API reference.

## Order of work (small PRs)
1. Copy and colour only: nav labels, `copy_ready` tone, neutral attention badge, Today section order, Run detail summary first. No API change.
2. `failure_kind` + migration + no automatic retry for outcomes + `StatusOut.buckets`.
3. Today hero with draft previews and the Hot leads strip; Needs a decision regrouped; Leads views.
4. Hot leads that could not be emailed (LinkedIn fallback), bell notice, tour and manual.

## Gate
- On a workspace with production-like data, the first screen shows emails ready (or the mailbox and hot leads) before any problem.
- No red appears on Today unless a mailbox, credits or a key is broken.
- The Needs a decision badge equals the number of leads with an action only a person can take.
- Every hot lead that is screened out for want of an email appears on Hot leads.
- Playwright: the tour passes, the parity check passes, and the existing Review, Needs attention and LinkedIn tests are updated.

## Decisions on the open questions (2026-11-19)

1. **Retries:** outcomes are not dropped silently and not retried every few minutes. They carry a counter: asked again 24 hours later, 3 tries in all, then screened out. A broken step gets 5 tries. The lead shows "try 2 of 5".
2. **Names:** renamed. Emails ready, Hot leads, Needs a decision (the paths are unchanged).
3. **Approval:** a draft can be approved from Today's preview cards as well as from Review. One whose checks were skipped asks for a deliberate approval in Review.
