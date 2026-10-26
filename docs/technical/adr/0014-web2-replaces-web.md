---
type: reference
status: accepted
date: 2026-10-19
deciders: "@rahul-trip"
introduced_in: 4e554b9 (#10)
---

# 0014. web2 replaces the first web app

## Context

The first React app (`web/`) proved the API but had no design system. The operator needed a clearer interface: a funnel dashboard, a dual-pane review, a lead journey and a guided tour. A design system was produced in Google Stitch.

## Decision

A new React app, `web2/`, implements the Stitch design tokens (`docs/design.md`) and every screen. FastAPI serves `web2/dist`. `web/` is kept, unserved, until it is deleted. Both use a client generated from the API's OpenAPI document; both have Playwright tests against a real server with fake vendors.

## Consequences

- **Good:** one coherent UI; status words and colours in one file; a guided tour kept current by a test.
- **Bad:** until `web/` is deleted, CI builds, tests and audits two apps, and Dependabot covers only the old one ([R-16](../tech-debt-and-risks.md#r-16--p2--supply-chain-gaps-in-update-and-pinning-coverage)).
- **Follow-ups:** delete `web/`, its CI job and its Dependabot entry; add `web2/` to Dependabot.

## Alternatives considered

| Option | Why not |
|---|---|
| Restyle `web/` in place | Too many structural changes; a clean app was faster |
| Server-rendered pages | The operator workflows are interactive (polling, diffs, multi-step forms) |

## Evidence in the code

- `outbound/api/app.py` (`WEB_DIST` points at `web2/dist`); `web2/`; `docs/design.md`; `web2/e2e/`.
