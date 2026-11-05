# Agent Reference & Tooling

## Purpose
This document provides instructions and context for AI coding assistants working on the Outbound email campaign codebase.

## Design & UI System (`web2`)
- **Stitch Project**: `projects/7399113199558765054` ("Design System Generator")
- **Design Tokens**: `docs/design.md` defines colors, typography (Inter + JetBrains Mono), spacing (4px unit rhythm), and elevation tiers.
- **Screens Implemented in `web2/src/pages/`**:
  - `Dashboard.tsx`: Variant 2 (`b82c0f5861154818bfab6fc0ea6a9c98`) with 8-stage interactive funnel centerpiece, bottleneck action callouts, drop-out status strip, and dual spend/quality telemetry cards.
  - `Review.tsx`: Dual-pane review matching Stitch screen `7fc684982cf04eb5aa794b19102079f2`, word count targets, lint alerts, diff preview, compliance lock, approve/reject mutations.
  - `Attention.tsx`: Needs Attention triage matching Stitch screen `e76d9620c9de4adebf7e85f95a860052`, filterable held/failed leads, instant release and retry.
  - `Leads.tsx`: Leads data table matching Stitch screen `df01f6be973a49f69df1f062bbf22c75`, search, status filter, hold reason filter, pagination.
  - `LeadDetail.tsx`: Matching Stitch screen `639e16bf31e743c9b98ea714433f1c5d` ("Halden Power Ltd"), contacts list, add-person form, messages history, research profile, vendor waterfall ledger, safeguarded delete modal (`POST /api/companies/{company_id}/delete`), and link to Pipeline Journey.
  - `LeadJourney.tsx`: Interactive 8-stage execution stepper with status nodes, "What happens next" banner, stage facts, vendor calls & latency telemetry, and intake origin metadata (`GET /api/companies/{company_id}/journey`).
  - `Targets.tsx`: Add Leads matching Stitch screen `80739578575147c19f28442a738b5f6e`, manual input, drag-and-drop CSV/XLSX uploader (`/api/targets/upload`), dry-run validation, and intake results table.
  - `Runs.tsx`: Pipeline Runs matching Stitch screen `0faacf7d709347f68e0d06dd45836a99`, run trigger form (mode, limit, discovery count), live polling, execution history table with cancellation support.
  - `Reports.tsx`: Analytics matching Stitch screen `0fba433f9aa348948e0642f15fbf750d`, 30-day spend burn, per-prospect budget efficiency bar against $0.50 cap, provider consumption, 80% unedited copy compliance tracker.
  - `Campaigns.tsx`: Dedicated outreach campaigns dashboard with ICP narrative editor, minimum fit score slider, custom research questions, target persona titles, and follow-up cadence scheduling.
  - `Mailboxes.tsx`: Sending mailbox connectivity, aggregate daily capacity metrics, and live DNS diagnostics (SPF, DKIM, DMARC) with `POST /api/settings/mailboxes/{mailbox_id}/dns-check`.
  - `Compliance.tsx`: Country cold-email rules (`GET`/`PUT /api/settings/policies/{country_code}`), corporate subscriber requirements, statutory footer editor, live suppression registry, and GDPR Article 17 Right to be Forgotten erasure (`POST /api/privacy/forget`).
  - `Settings.tsx`: Tabbed configuration suite covering Workspace budget ceiling (`PUT /api/settings/workspace`), Sender Identity profile narrative & legal disclosures (`PUT /api/settings/sender-profile`), connected Mailboxes, Suppression registry, and Campaigns.

## Key Architecture Rules
- Strictly follow layer boundaries: `domain` -> `db`/`providers` -> `metering` -> `stages` -> `runner` -> `services` -> `pipeline` -> `cli`/`api`/`worker`.
- Pay-as-you-go waterfall for contact finding/verification with strict meter guards.
- Keep `CLAUDE.md`, `agent.md`, and `memory.md` updated across tasks.
