---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-18 (docs read; not yet checked with a live key)
applies_to: Phase 6
---

# Generect

| | |
|---|---|
| **Role** | Email finder, billed only for a valid address |
| **Port** | `EmailFinder` |
| **Adapter** | `outbound/providers/adapters/generect.py::GenerectFinder` |
| **Registry** | `generect` (in `FINDER_CHAIN`) |
| **Settings** | `GENERECT_API_KEY` |
| **Price** | `generect:find` 20,000 micro-USD (its documented example, $0.02) |
| **Cache** | `find` on `{person, domain}`, 90 days |
| **Status** | Built from the vendor's own documentation (read 2026-11-18). **Not yet checked live**: confirm with `uv run python -m scripts.live_check --finders --only find:generect` and the bake-off before relying on it (Scrubby's first adapter was wrong in this way, R-39). |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `find(person, domain)` | `POST https://api.generect.com/api/v1/email/find/`, body `{first_name, last_name, domain}` | `Authorization: Token <key>` |

From Generect's OpenAPI file, `https://docs.generect.com/api-reference/openapi.yaml`.

## Mapping

| Generect | Ours |
|---|---|
| `data.valid_email` with `data.result: valid` | `FinderResult(email, confidence 0.9, billed = meta.amount_charged > 0)` |
| `data.valid_email: null`, or any other `result` | No address, not billed |

## Errors

401 and 403 raise `ProviderAuthError`; **402** raises `BudgetExceeded`; 429 and 5xx are retried.

## Tests and fixtures

`tests/providers/test_generect.py`. Fixtures in `tests/providers/fixtures/generect/`, from the vendor's OpenAPI examples.

## Data sent to the vendor

The person's first and last name and the company domain.
