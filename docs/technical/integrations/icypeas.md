---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-18 (docs read; not yet checked with a live key)
applies_to: Phase 6
---

# Icypeas

| | |
|---|---|
| **Role** | Email finder, one credit per address found |
| **Port** | `EmailFinder` |
| **Adapter** | `outbound/providers/adapters/icypeas.py::IcypeasFinder` |
| **Registry** | `icypeas` (in `FINDER_CHAIN`) |
| **Settings** | `ICYPEAS_API_KEY` |
| **Price** | `icypeas:find` 19,000 micro-USD (an estimate from its public plans) |
| **Cache** | `find` on `{person, domain}`, 90 days |
| **Status** | Built from the vendor's own documentation (read 2026-11-18). **Not yet checked live**: confirm with `uv run python -m scripts.live_check --finders --only find:icypeas` and the bake-off before relying on it (Scrubby's first adapter was wrong in this way, R-39). |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| start | `POST https://app.icypeas.com/api/email-search`, body `{firstname, lastname, domainOrCompany}` → `{success, item: {_id, status: NONE}}` | `Authorization: <key>` (raw) |
| read | `POST https://app.icypeas.com/api/bulk-single-searchs/read`, body `{id}` → `{items: [{status, results: {emails: [{email, certainty}]}}]}` | same |

The search is asynchronous. The adapter reads the result every 3 seconds (the vendor allows 30 reads a minute) for up to about 25 seconds.

## Mapping

| Icypeas | Ours |
|---|---|
| `certainty` `ultra_sure` (0.99), `very_sure` (0.97), `probable` (0.9) | The best one is the address; every address is still verified by our own check |
| `undeliverable`, `not_found`, no emails | No address, not billed |
| Not finished after the polls | `ProviderError` (the lead waits and is tried again), **not** "nothing found" |

## Errors

401 raises `ProviderAuthError`; the result status `INSUFFICIENT_FUNDS` raises `BudgetExceeded`; HTTP 200 with `success: false` (a validation error) is a `ProviderError`; 429 is retried.

## Tests and fixtures

`tests/providers/test_icypeas.py`. Fixtures in `tests/providers/fixtures/icypeas/`.

## Data sent to the vendor

The person's first and last name and the company domain.
