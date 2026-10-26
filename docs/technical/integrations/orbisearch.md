---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# OrbiSearch

| | |
|---|---|
| **Role** | Email verifier only. OrbiSearch has no finder API |
| **Port** | `EmailVerifier` |
| **Adapter** | `outbound/providers/adapters/orbisearch.py::OrbiSearchVerifier` |
| **Registry** | `orbisearch` |
| **Settings** | `ORBISEARCH_API_KEY` |
| **Price** | `orbisearch:verify` 200 micro-USD |
| **Cache** | `verify`, 90 days |
| **Status** | Live-checked 2026-10-19 |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `verify(email)` | `GET https://api.orbisearch.com/v1/verify?email&timeout=25` | `X-API-Key` header |

The vendor accepts a timeout of 3–90 s (default 70). The adapter asks for 25 s so the answer arrives within `HttpClient`'s 30 s.

## Mapping

| OrbiSearch `status` | Ours |
|---|---|
| `safe` | `valid` |
| `risky` | `catch_all` |
| `invalid` | `invalid` |
| `unknown`, anything else | `unknown` |

`raw_status` keeps `status/substatus`.

## Tests and fixtures

`tests/providers/test_orbisearch.py`; fixtures in `tests/providers/fixtures/orbisearch/` (safe, risky, invalid, unknown).

## Data sent to the vendor

Email addresses.
