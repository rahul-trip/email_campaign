---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §5](../../PLAN.md#5-architecture); c3d3228 (#1)
---

# 0008. Vendors behind ports; vendor JSON never leaves its adapter

## Context

The vendor chain is provisional until a bake-off, and vendors change price, accuracy and API. Their response shapes differ and are sometimes poorly documented. Stages must not depend on any of that.

## Decision

Each kind of vendor is a `Protocol` in `outbound/providers/ports.py` (finder, verifier, resolver, search, LLM, company registry, mailbox) with frozen Pydantic result models (`extra="forbid"`). Each vendor has one adapter that maps its JSON into those models and raises typed `ProviderError`s. A registry builds adapters by name from settings. All HTTP goes through one `HttpClient` that owns timeouts and retries; adapters never retry.

## Consequences

- **Good:** swapping a vendor is one adapter, one registry entry, one price and a config line; stages and tests use fakes at the port; malformed vendor answers fail at the edge.
- **Bad:** every vendor needs fixtures built from its documentation; quirks the docs omit are found only by a live check (Scrubby, [R-09](../tech-debt-and-risks.md#r-09--p1--vendors-the-provider-chain-is-unproven-e5-d5)).
- **Follow-ups:** binding rule 2 in [CLAUDE.md](../../../CLAUDE.md); [add a vendor adapter](../guides/add-a-vendor-adapter.md).

## Alternatives considered

| Option | Why not |
|---|---|
| Call vendor SDKs from stages | Vendor types leak everywhere; tests need network or heavy mocks |
| A generic HTTP-integration framework | Speculative; a Protocol per role is enough |

## Evidence in the code

- `outbound/providers/ports.py`, `outbound/providers/adapters/`, `outbound/providers/registry.py`, `outbound/providers/http.py::HttpClient`.
- `tests/contract/` (shared contract tests per port); `tests/providers/` (one file per adapter).
