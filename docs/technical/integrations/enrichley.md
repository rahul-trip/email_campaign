---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Enrichley

| | |
|---|---|
| **Role** | Catch-all resolver that answers at once |
| **Port** | `CatchAllResolver` |
| **Adapter** | `outbound/providers/adapters/enrichley.py::EnrichleyResolver` |
| **Registry** | `enrichley` (as `CATCH_ALL_RESOLVER`) |
| **Settings** | `ENRICHLEY_API_KEY` |
| **Price** | `enrichley:resolve` 11,800 micro-USD |
| **Cache** | The answer is stored as a `resolve` hit, 90 days |
| **Status** | Not yet checked live |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `submit(email)` | `POST https://api.enrichley.io/api/v1/validate-single-email` with `{email}` | `X-Api-Key` header |
| `poll(ticket)` | none: returns the result the ticket already carries | — |

## Mapping

| Enrichley `result` | Ours |
|---|---|
| `ok`, `catch_all_validated` | `valid` (the address becomes `catch_all_resolved`) |
| `invalid` | `invalid` |
| `catch_all`, `unknown`, anything else | `unresolved` (the address becomes `catch_all_unverified`) |

`billed` follows `credits_consumed` (true if absent).

## Tests and fixtures

`tests/providers/test_enrichley.py` with the resolver contract; fixtures in `tests/providers/fixtures/enrichley/` (ok, catch_all_validated, invalid, catch_all, unknown).

## Data sent to the vendor

Email addresses at catch-all domains.
