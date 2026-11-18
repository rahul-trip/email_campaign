---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-18 (docs read; not yet checked with a live key)
applies_to: Phase 6
---

# Prospeo

| | |
|---|---|
| **Role** | Email finder (Enrich Person), paid per address found |
| **Port** | `EmailFinder` |
| **Adapter** | `outbound/providers/adapters/prospeo.py::ProspeoFinder` |
| **Registry** | `prospeo` (in `FINDER_CHAIN`) |
| **Settings** | `PROSPEO_API_KEY` |
| **Price** | `prospeo:find` 39,000 micro-USD (an estimate from its public plans) |
| **Cache** | `find` on `{person, domain}`, 90 days |
| **Status** | Built from the vendor's own documentation (read 2026-11-18). **Not yet checked live**: confirm with `uv run python -m scripts.live_check --finders --only find:prospeo` and the bake-off before relying on it (Scrubby's first adapter was wrong in this way, R-39). |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `find(person, domain)` | `POST https://api.prospeo.io/enrich-person`, body `{only_verified_email: true, data: {first_name, last_name, company_website}}` | `X-KEY` header |

Prospeo's older email-finder endpoint is deprecated in favour of this one.

## Mapping

| Prospeo | Ours |
|---|---|
| `person.email.status: VERIFIED` with an address | `FinderResult(email, confidence 0.95, raw_status verified)`; one credit |
| HTTP 400 `error_code: NO_MATCH` (also when no verified address exists) | No address, not billed (not an error) |
| An address with `*` in it, or any status other than `VERIFIED` | No address (a masked address is not usable) |

## Errors

HTTP 400 carries an `error_code`, which `ProviderError.body` keeps for the adapter: `INSUFFICIENT_CREDITS` raises `BudgetExceeded`, `INVALID_API_KEY` raises `ProviderAuthError`, `NO_MATCH` is a miss, any other code is a `ProviderError`. 429 and 5xx are retried.

## Tests and fixtures

`tests/providers/test_prospeo.py`. Fixtures in `tests/providers/fixtures/prospeo/`, from the vendor's documented examples (the matched address is filled in, as the docs mask it).

## Data sent to the vendor

The person's first and last name and the company website.
