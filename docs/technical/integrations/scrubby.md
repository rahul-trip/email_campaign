---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-16 (phase-6/lead-quality-part-2)
applies_to: Phase 3b
---

# Scrubby

| | |
|---|---|
| **Role** | Asynchronous catch-all resolver (the default `CATCH_ALL_RESOLVER`). Validation takes 24–72 hours |
| **Port** | `CatchAllResolver` |
| **Adapter** | `outbound/providers/adapters/scrubby.py::ScrubbyResolver` |
| **Registry** | `scrubby` |
| **Settings** | `SCRUBBY_API_KEY`; `SCRUBBY_BASE_URL` is optional (default `https://api.scrubby.io`) |
| **Price** | `scrubby:resolve`: not public (`None`, recorded as 0). Deep verification uses more credits per address than a plain check |
| **Cache** | An answer from `poll` is stored as a `resolve` hit, 90 days |
| **Status** | Live-checked 2026-11-16: a deep batch is accepted and polls as pending. A finished batch has not been seen yet ([R-39](../tech-debt-and-risks.md#r-39--p1--catch-all-resolver-every-scrubby-call-was-a-404-and-an-outage-held-leads-for-good--closed-2026-11-16)) |

Documentation: `https://docs.scrubby.io`; the OpenAPI file it renders is `https://docs.scrubby.io/scrubby-openapi.json`.

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `submit(email)` | `POST /validate_bulk_emails/deep/` with `{"email": [address]}`; answers **202** with an `identifier` | `x-api-key` header |
| `poll(ticket)` | `POST /fetch_bulk_results/deep` with `{"identifier": ...}`; `status` is `processing` or `completed` | `x-api-key` |

Deep verification is the part of Scrubby that settles an address on a catch-all domain, and takes up to 24 hours. `submit` never carries a result: the lead is held as `catch_all_resolving`, and the [poller](../lld/stage-email.md#the-poller) asks every 6 hours from `tick`. The 202 is Scrubby's success, so its `HttpClient` is built with `accepted_is_final=True`; the default would retry it and submit, and bill, the batch again. Scrubby's instant `POST /validate_email` (a plain check, 100-second timeout) is not used: it does not settle catch-alls.

## Mapping

| Scrubby `results[address].result` | Ours |
|---|---|
| `pending`, or the batch `status` is `processing` | No answer yet |
| `Valid` | `valid` |
| `Invalid` | `invalid` |
| `Risky`, `Unknown`, or no entry for the address | `unresolved` |

## Tests and fixtures

`tests/providers/test_scrubby.py`. In `tests/providers/fixtures/scrubby/`, every fixture follows the shapes in the published OpenAPI file (`DeepBulkEmailResponse`, `FetchResultResponse`).

## Data sent to the vendor

Email addresses at catch-all domains.
