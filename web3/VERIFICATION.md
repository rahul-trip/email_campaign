# web3 pre-build verification (2026-11-17)

web3 replaces web2 over the **same API and the same database**. This page records what was
checked before any screen is coded: that no feature is lost, and that every piece of data the
Stitch mockups show really exists. Source of truth: `web3/openapi.json` (generated from the
FastAPI app), `web2/src`, and the backend code read through CodeGraph.

## 1. Feature parity

- web2 calls **181 distinct API routes**; every one exists in the API (none dead).
- `GET /api/admin/audit.csv` looked unused, but both apps call it through a plain download link
  ("Export CSV" on the admin Audit log), which the parity script does not count. Nothing is
  unused.
- `node web3/scripts/check-parity.mjs` fails while web3 is missing any route web2 calls. It runs
  in CI for the whole migration; web2 is retired only when it passes. Every row of
  `FEATURE_MAP.md` gives the feature's web3 home.

## 2. Mockup data against the API

Legend: **✓** already returned · **◐** computed in the browser from existing responses ·
**＋** needs a small read-only endpoint or query parameter (no migration) · **✕** not real today:
dropped or reworded in the build.

### Today
| Mockup element | Source | Verdict |
|---|---|---|
| Pipeline counts per stage | `GET /api/status` `by_status` | ✓ |
| "N waiting for review", oldest waited X | `/api/status` `waiting_for_review`; `/api/review` `message.created_at` | ✓ / ◐ |
| Needs you (holds, failures, credit waits) | `/api/status` `held`; `/api/companies?hold_reason=…`; `failed_stage`, `last_error` | ✓ |
| Activity feed | `/api/me/notifications` (activity notices) | ✓ |
| Next discovery, paused at 50 drafts | `/api/runs/auto-discovery` (`next_search`, `review_limit`, `waiting_for_review`, `reason`) | ✓ |
| Credits meter | `/api/usage` `steps[].remaining/limit`, `period_end` | ✓ |
| Approved unedited % | `/api/reports/quality` `unedited_share` | ✓ |
| Spend this month ($) | `/api/reports/cost?days=` `total` | ✓ |
| Week-over-week deltas | reports with `days=7` and `days=14`, subtracted | ◐ |
| Sparklines (per-day series) | none | ＋ `GET /api/reports/daily?days=14` (grouped from existing `events`, `messages`, `provider_calls`) |
| Fit-score histogram | none (would need every company) | ＋ `GET /api/reports/fit` (counts per score band, one query) |
| Where good leads come from | `/api/reports/sources` | ✓ |
| "Worker ticked 4 min ago" | worker keeps last tick in memory only | ✕ → show "last discovery" (`auto-discovery.last_search`) and the latest run's time |
| **Reply rate, emails sent "vs benchmark"** | replies are Phase 4, not built | ✕ → replaced by Sent (`messages.sent_at`) and Approved unedited |
| "Spend vs budget" ring | workspaces have credits, not a $ budget | ✕ → credits ring |
| Review streak, "4 of 16 today", daily goal | review decisions are `events`; no aggregate; no goal setting | ＋ streak/today from the daily endpoint; ✕ goals (would need storage) |

### Review
| Element | Source | Verdict |
|---|---|---|
| Queue, email, subject, lint hints | `/api/review`, `/api/review/{id}` (`message.lint_report`, `skips`, `history`) | ✓ |
| Approve / reject / edit / AI rewrite | `…/approve`, `reject`, `revise`, `rewrite` | ✓ |
| Fit breakdown (must-haves, signals, rule-outs, evidence) | `company.research` holds `Qualification.to_json()` | ✓ |
| Verification path and cost | `/api/companies/{id}/waterfall`, `journey.total_cost_micro_usd` | ✓ |
| Keyboard J/K/A/E/R | browser | ◐ |

### Leads
| Element | Source | Verdict |
|---|---|---|
| Name, domain, status, fit, hot, source, country, updated | `/api/companies` `CompanyOut` | ✓ |
| Filters: status, hold, campaign, search, credit wait | query params exist | ✓ |
| Filters/views: fit ≥ N, Hot, source, country; sort | not supported as params | ＋ add `min_fit`, `hot`, `source`, `country`, `sort` to `GET /api/companies` (columns exist) |
| Contact name/title, email-verification chip, cost per row | not in `CompanyOut`; would be one call per row | ＋ optional `include=summary` on the list (one join, no migration) — or the build omits these columns |
| Stage distribution bar | `/api/status` | ✓ |

### Lead detail, Runs, Campaigns, Reports, LinkedIn, Policies, Settings, Admin
All shown data is returned today (`LeadOut`, `journey`, `timeline`, `waterfall`, `directory`,
`policy-skip`; `RunOut.counts`, run `leads/candidates/searches/calls`; `CampaignOut` with
`icp_brief`, `brief_gaps`, `min_fit_score`; `reports/*` with `days`; `LinkedInDraftOut`;
policies, suppressions, forget; `MailboxOut` with `dns_check`, `last_checked_at`; admin routes).
Exceptions:
- **Start-run drawer**: `POST /api/runs` takes `discover` 1–50, `limit`, `mode`, `only`,
  `skip_directory`. Sources are chosen by the engine (`plan_sources`), the fit gate is always on.
  The mockup was corrected: count 10/25/50, sources read-only, one real toggle (skip directory).
  "Which sources this brief will use" before running is ＋ (`GET /api/runs/plan`, read-only) or
  shown after the run starts.
- **Per-campaign stats** on Campaigns: ◐ from `/api/companies?campaign_id=` totals (one active
  campaign per workspace).
- **Policies "requests log"**: remove-my-data requests are not exposed to workspaces → ✕.
- **Suppression removal**: no DELETE today (web2 has none either) → unchanged.

### Onboarding and empty state
| Element | Source | Verdict |
|---|---|---|
| Steps and ticks | `/api/setup` | ✓ |
| Read my website → draft profile | `POST /api/setup/profile-draft` | ✓ |
| Who signs: name, title, legal name, address | sender profile `signature_name/title`, `legal_name`, `postal_address` | ✓ |
| Signature style picker | no field | ✕ (or map to `style_examples` later) |
| Address autocomplete | needs an outside service | ✕ |
| Who to reach: titles, countries, size, must-haves/signals/rule-outs | `POST /api/setup/campaign-draft`, campaign `target_titles`, `icp_brief` (Brief: regions, size, criteria) | ✓ |
| Market estimate "~3,400 companies", sample companies | none | ✕ (already removed) |
| First leads: discovery / upload / one company | `POST /api/runs`, `/api/targets/upload`, `/api/targets` | ✓ |
| Live candidates dropping in | poll `/api/runs/{id}/candidates` | ✓ |
| Mailbox connect + DNS | `/api/mailboxes/*`, `dns-check` | ✓ |
| Welcome goal quiz | no storage | ◐ steers the next screen only (not saved) |
| "Email me when drafts are ready" | no such notification email | ✕ |
| Starter campaign templates (empty state) | presets that pre-fill `POST /api/settings/campaigns` | ◐ |
| "Explore with sample data" | workspaces start blank; no demo mode | ✕ unless approved (would be a server seed) |

## 3. Backend changes the build needs

All are **read-only, additive, and need no migration**. Each keeps web2 working.

1. `GET /api/reports/daily?days=14` — per-day counts (approved, sent, leads made, spend, reviews)
   from existing tables. Powers sparklines, deltas and the review streak.
2. `GET /api/reports/fit` — counts of companies per fit band for the active campaign.
3. `GET /api/companies`: new optional params `min_fit`, `hot`, `source`, `country`, `sort`.
4. *(optional)* `GET /api/companies?include=summary` — primary contact, email status, cost.
5. *(optional)* `GET /api/runs/plan` — the sources discovery would use for the active brief.

Each gets a permission (`require(...)`), tests on SQLite and Postgres, workspace scoping, and the
doc updates the repo rules ask for. **No database migration is needed for anything in the
mockups** once the ✕ items are dropped.

## 4. Decisions (operator, 2026-11-17)

- **All ✕ items are dropped or reworded** to real data: Sent and Approved unedited replace reply
  rate; last discovery and latest run replace the worker heartbeat; a credits ring replaces the
  $ budget; no goals, signature-style picker, address autocomplete, requests log, drafts-ready
  email, or sample-data mode.
- **All five backend additions are built** (1–5 above), read-only, no migration, web2 unaffected.
