# Agent Reference & Tooling

## Purpose
This document gives instructions and context for AI coding assistants working on the Outbound email campaign codebase. The source of truth is `CLAUDE.md` and the docs it names. This file is a quick map.

## Web app (`web2`)
- React + Vite + TanStack Router, served by `outbound serve` from `web2/dist`. Design tokens are in `docs/design.md`.
- Routes under `/w/{slug}` are a workspace's pages, built in `web2/src/main.tsx`. Pages outside a workspace (sign-in, invitations, the workspace chooser, "Get started") are in `web2/src/app/Public.tsx`.
- Workspace pages in `web2/src/pages/`:
  - `Dashboard.tsx`: funnel, bottleneck callouts, spend and quality cards.
  - `Review.tsx`: approve or reject a drafted email.
  - `Attention.tsx`: held and failed leads, with release and retry.
  - `Leads.tsx`, `LeadDetail.tsx`, `LeadJourney.tsx`: lead list, lead page with contacts and vendor ledger, and the stage-by-stage journey.
  - `Targets.tsx`: add leads by hand or by CSV/XLSX upload.
  - `Runs.tsx`, `RunDetail.tsx`: run trigger, history and detail.
  - `Reports.tsx`: spend and copy statistics.
  - `Campaigns.tsx`, `Mailboxes.tsx`, `Compliance.tsx`, `Onboarding.tsx`.
  - `Settings.tsx` with tabs in `settingsTabs.ts`: setup, profile, mailboxes, limits, plan, team (`SettingsTeam.tsx`: invitations, roles, join code and join requests), integrations (`SettingsIntegrations.tsx`), account.
- The platform admin console is `web2/src/admin/` (`/admin`): Overview, Customers, Users (includes inviting someone to Outbound), Plans, Vendors, Directory, Audit, Settings.
- The header has a notifications bell (`web2/src/components/Notifications.tsx`) for join requests and their answers.
- The product tour is `web2/src/tour/steps.ts`. Every new screen or element needs a step, a `data-tour` attribute and the "Guided tour" part of `docs/USER_MANUAL.md`.
- Stitch project for the design: `projects/7399113199558765054` ("Design System Generator"). Dashboard Variant 2 is `b82c0f5861154818bfab6fc0ea6a9c98`.

## Key architecture rules
- Layers: `domain` -> `db`/`providers` -> `metering` -> `stages` -> `runner` -> `services` -> `pipeline` -> `cli`/`api`/`worker`. `uv run lint-imports` checks this.
- Every API route declares its permission with `require(Permission.X)`. The route-walk test fails otherwise. Routes outside any workspace (`/api/me/*`) are listed as open in `tests/api/test_permissions.py`.
- Platform tables (`users`, `memberships`, `auth_tokens`, `join_requests`, `notifications`, ...) have no row-level security and are reached only through `outbound/db/identity.py`.
- Every paid vendor call goes through the meter in `outbound/metering/`.
- The schema changes only through Alembic, and `docs/technical/data/schema.md` is updated in the same PR. The latest migration is `0017` (join codes, join requests, notifications).

## Working conventions
- One branch per task, named `phase-N/<task>`, and a PR into `main`.
- Never commit `.env` files or private data.
- Run `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports && uv run pytest` before a PR. For web changes also `cd web2 && npm run typecheck && npm run build && npx playwright test`.
