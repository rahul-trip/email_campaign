# Assistant Memory

## Active Integrations & External Tooling
- **LLM Model**: `nvidia/nemotron-3-ultra-550b-a55b:free` via OpenRouter (`openai_compatible` provider). Changed from `nemotron-3-super-120b-a12b:free` on 2026-10-21. Updated in both `.env` and Doppler (`outbound/dev` config).
- **Stitch by Google (MCP Server)**: Active and connected.
  - Project: **Design System Generator** (`projects/7399113199558765054`)
  - Associated Design System: `Outbound` (matches `docs/design.md`)
  - Base Screen: `c3ee94dee52547818ee58ce329eb84a2` ("Outbound — Home Dashboard")
  - Generated Variants (Oct 19, 2026):
    - Variant 1 (Operational Triage): `0449b99b8e5c4589bca0ffc0a939cfd2`
    - **Variant 2 (Selected - Pipeline Funnel Flow)**: `b82c0f5861154818bfab6fc0ea6a9c98`
    - Variant 3 (Executive Telemetry & Unit Economics): `24c583aeea924bc3b43a8a590e5f92f1`

## Project Status Summary
- **Current Phase**: Phase 3b (hardening) / Phase 3 (FastAPI + React web frontend).
- **Frontend Workspaces**:
  - `web/`: Original React frontend with router, components, tour, and Playwright tests.
  - `web2/`: Modernized UI implementing Stitch designs / Tailwind with `docs/design.md` tokens.
    - All application screens implemented, wired to OpenAPI endpoints, and build-verified (`npm --prefix web2 run build` passed with zero errors):
      - **Dashboard (`/`)**: Variant 2 centerpiece featuring interactive 8-stage funnel nodes, bottleneck action callouts, drop-out status strip, and dual spend/quality telemetry.
      - **Review Queue (`/review`)**: Dual-pane review matching Stitch screen `7fc684982cf04eb5aa794b19102079f2`, word count targets, lint alerts, diff preview, compliance lock, approve/reject mutations.
      - **Needs Attention (`/attention`)**: Filterable held/failed lead triage matching Stitch screen `e76d9620c9de4adebf7e85f95a860052`, instant hold release (`/release-hold`) and retry (`/retry`).
      - **Leads Directory (`/leads`)**: Matching Stitch screen `df01f6be973a49f69df1f062bbf22c75`, search, status filter, hold reason filter, pagination.
      - **Lead Detail (`/leads/$companyId`)**: Matching Stitch screen `639e16bf31e743c9b98ea714433f1c5d` ("Halden Power Ltd"), contacts list, add-person form, messages history, research profile, vendor waterfall ledger, permanent delete modal (`POST /api/companies/{company_id}/delete`), and direct link to Pipeline Journey.
      - **Lead Journey (`/leads/$companyId/journey`)**: Interactive 8-stage timeline stepper with status indicators (done, current, waiting, held, failed), "What happens next" banner, stage facts, vendor calls & latency telemetry, and intake origin metadata.
      - **Add Leads (`/targets`)**: Matching Stitch screen `80739578575147c19f28442a738b5f6e`, manual target input, drag-and-drop CSV/XLSX uploader (`/api/targets/upload`), dry-run validation, and intake results table.
      - **Runs (`/runs`)**: Matching Stitch screen `0faacf7d709347f68e0d06dd45836a99`, run trigger form (mode, limit, discovery count), live polling, execution history table with cancellation support.
      - **Reports (`/reports`)**: Matching Stitch screen `0fba433f9aa348948e0642f15fbf750d`, 30-day spend burn, per-prospect budget efficiency bar against $0.50 cap, provider consumption, 80% unedited copy compliance tracker.
      - **Campaigns (`/campaigns`)**: Dedicated campaigns dashboard with ICP narrative editor, minimum fit score slider, custom research questions, target persona titles, and follow-up cadence scheduling (`GET /api/settings/campaigns`, `POST`, `PATCH`).
      - **Mailboxes (`/mailboxes`)**: Sending mailbox connectivity, aggregate daily capacity metrics, and live DNS diagnostics (SPF, DKIM, DMARC) with `POST /api/settings/mailboxes/{mailbox_id}/dns-check`.
      - **Compliance (`/compliance`)**: Regulatory policies by country (`GET`/`PUT /api/settings/policies/{country_code}`) with rule selection, corporate subscriber requirements, statutory footer editor, live suppression registry, and GDPR Article 17 Right to be Forgotten erasure (`POST /api/privacy/forget`).
      - **Settings (`/settings`)**: Tabbed configuration suite covering Workspace budget ceiling (`PUT /api/settings/workspace`), Sender Identity profile narrative & legal disclosures (`PUT /api/settings/sender-profile`), connected Mailboxes, Suppression registry, and Campaigns.
      - **Sign In (`/`)**: Unauthenticated modal matching Stitch screen `7ba17ef95cac49efbc116e6250230618`.
