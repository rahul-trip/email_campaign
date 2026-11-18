---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-18 (docs read; not yet checked with a live key)
applies_to: Phase 6
---

# Anymail Finder

| | |
|---|---|
| **Role** | Email finder, paid per valid address |
| **Port** | `EmailFinder` |
| **Adapter** | `outbound/providers/adapters/anymailfinder.py::AnymailFinder` |
| **Registry** | `anymailfinder` (in `FINDER_CHAIN`) |
| **Settings** | `ANYMAILFINDER_API_KEY` |
| **Price** | `anymailfinder:find` 29,000 micro-USD (an estimate from its public plans; set `PROVIDER_PRICES` to your plan's) |
| **Cache** | `find` on `{person, domain}`, 90 days |
| **Status** | Built from the vendor's own documentation (read 2026-11-18). **Not yet checked live**: confirm with `uv run python -m scripts.live_check --finders --only find:anymailfinder` and the bake-off before relying on it (Scrubby's first adapter was wrong in this way, R-39). |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `find(person, domain)` | `POST https://api.anymailfinder.com/v5.1/find-email/person`, body `{domain, first_name, last_name, linkedin_url?}` | `Authorization: <key>` (raw key, no `Bearer`) |

No rate limit is documented; a search usually answers in about 3 seconds, and the vendor advises a long timeout (the adapter waits up to 90 seconds).

## Mapping

| Anymail Finder | Ours |
|---|---|
| `email_status: valid`, `valid_email` | `FinderResult(email, confidence 0.95, billed = credits_charged > 0)` |
| `not_found`, `blacklisted` (and, since 2026-10-05, what was `risky`) | No address, not billed |
| `credits_charged: 0` with a valid address (a repeat within 30 days) | The address, not billed |

## Errors

401 raises `ProviderAuthError`; **402** (`upgrade_needed`, no credits) raises `BudgetExceeded`, so the worker pauses the finder and staff are told; 5xx and network errors are retried.

## Tests and fixtures

`tests/providers/test_anymailfinder.py` runs the shared finder contract and the cases above. Fixtures in `tests/providers/fixtures/anymailfinder/`, taken from the vendor's example responses.

## Data sent to the vendor

The person's first and last name, the company domain and, when known, their LinkedIn address.
