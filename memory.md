# Assistant Memory

## LLM model
- **Production and dev**: DeepSeek served by DeepInfra. `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=https://api.deepinfra.com/v1/openai`, `LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash-1017`. Set in Doppler `outbound/dev` and `outbound/prd` and mirrored in the root `.env`.
- The earlier OpenRouter setup (Nemotron, `nvidia/nemotron-3-...`) was replaced. Do not use it.
- The code defaults in `outbound/config.py` (`anthropic`, `claude-sonnet-5-5`) are only fallbacks. The real values come from the environment.
- `LLM_PRICES` must match the model's prices (3b B5).

## Stitch (design)
- Stitch MCP is connected. Project: **Design System Generator** (`projects/7399113199558765054`), design system `Outbound` (matches `docs/design.md`).
- Base screen `c3ee94dee52547818ee58ce329eb84a2` ("Outbound — Home Dashboard"). Dashboard Variant 2 (`b82c0f5861154818bfab6fc0ea6a9c98`) is the one implemented.

## Project status (2026-11-06)
- Phases 6a–6d, 4a, 6g and the deploy fixes are merged to `main`.
- Phase 6h (owners-and-join-requests, migration 0017) is merged as PR #40. The join-request flow is in production code but may not be on the VM yet: it needs a deploy with `ref=main`.
- **Discovery and qualification** is built on four stacked local branches, not pushed: `phase-6/discovery-brief` (0018) → `-sources` (0019) → `-qualification` → `-more-sources`. All checks pass (2063 Python tests, 880 on Postgres, 38 Playwright). A final whole-branch review found 5 important issues, all fixed. 11 minor ones are deferred and listed under *Left* in `docs/phases/PROGRESS-6.md` (Discovery and qualification).
- **Open live checks for discovery:** Exa and Companies House advanced search against real keys (R-30), whether the YC mirror is fresh (R-29), and one discovery run each for a startup campaign and a UK SME campaign.
- Still open: `phase-6/technical-docs` (19 commits not on `main`) and `phase-3b/web2` (2 commits not on `main`).
- Permanent constraints: no separate owner role (admin is the top role). A workspace's creator becomes an admin.

## How the operator works
- The operator opens pull requests themselves. Commit on the task branch, but never push or create a PR.
- `apgent.md` was a stray symlink to `agent.md` and was removed on 2026-11-06. `agent.md` is the single agent file.
