---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §5](../../PLAN.md#5-architecture); first committed in c3d3228 (#1)
---

# 0001. One modular monolith in layers

## Context

The engine is built and run by one developer for one operator, at 5–50 prospects a week. The legacy `agent/` package mixed vendor calls, model calls and file I/O in one flow, which made it hard to test and to change a vendor. The system needs strong internal boundaries (the domain rules must be testable without I/O; vendors must be swappable), but nothing about its load or team needs separate deployables.

## Decision

We build one Python package, `outbound/`, in layers that import only downward: domain → db / providers → metering → stages → runner → services → pipeline → cli / api / worker. The rules are enforced by import-linter contracts and a ruff ban, not by convention alone. The API, the worker and the CLI are entry points into the same package and run from the same image.

## Consequences

- **Good:** one codebase, one image, one deploy; refactoring across layers is a normal PR; rules live in a domain layer with no I/O, so most tests need no database.
- **Bad:** one process failing takes all its responsibilities with it; scaling is vertical only; the boundaries hold only while the contracts are kept in CI.
- **Follow-ups:** binding rule 1 in [CLAUDE.md](../../../CLAUDE.md); `uv run lint-imports` in CI and pre-commit.

## Alternatives considered

| Option | Why not |
|---|---|
| Microservices (research, enrichment, copy, mail) | Network boundaries, deploys and failure modes for no load or team benefit |
| A plugin framework for vendors | Speculative; ports and adapters give the same swap with less machinery |
| Keep extending the legacy `agent/` package | No layering, no tests at the boundaries, vendor JSON everywhere |

## Evidence in the code

- `pyproject.toml` `[tool.importlinter]`: three contracts (layers; the domain does no I/O; providers and db are independent).
- `pyproject.toml` ruff `banned-api`: `outbound.db.models` only inside `outbound/db`.
- `outbound/bootstrap.py` and `outbound/pipeline.py`: the single composition root.
