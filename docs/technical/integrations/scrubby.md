---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Scrubby

| | |
|---|---|
| **Role** | Asynchronous catch-all resolver (the default `CATCH_ALL_RESOLVER`). Validation takes 24–72 hours |
| **Port** | `CatchAllResolver` |
| **Adapter** | `outbound/providers/adapters/scrubby.py::ScrubbyResolver` |
| **Registry** | `scrubby` |
| **Settings** | `SCRUBBY_API_KEY` and **`SCRUBBY_BASE_URL`** (required; no default) |
| **Price** | `scrubby:resolve`: not public (`None`, recorded as 0) |
| **Cache** | An answer from `poll` is stored as a `resolve` hit, 90 days |
| **Status** | **Fails the live check** (2026-10-19): the guessed `api.scrubby.io` accepts the connection but never answers. Unproven ([R-09](../tech-debt-and-risks.md#r-09--p1--vendors-the-provider-chain-is-unproven-e5-d5)) |

> **Written from a partial reference.** The public documentation confirms the `x-api-key` header, `POST /add_email`, `GET /fetch_email/{email}`, a `pending` status, and a limit of 10 requests a second. It does **not** state the base URL, the request body, or the final result values. Until a live key confirms them, treat this adapter as unverified. Consider `enrichley` as the resolver meanwhile.

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `submit(email)` | `POST <SCRUBBY_BASE_URL>/add_email` with `{email}` (assumed) | `x-api-key` header |
| `poll(ticket)` | `GET <SCRUBBY_BASE_URL>/fetch_email/<email>` | `x-api-key` |

`submit` never carries a result: the lead is held as `catch_all_resolving`, and the [poller](../lld/stage-email.md#the-poller) asks every 6 hours from `tick`. Nothing schedules `tick` in production ([R-02](../tech-debt-and-risks.md#r-02--p1--pipeline-scheduled-work-never-runs-in-production-b7)).

## Mapping

| Scrubby `status` | Ours |
|---|---|
| `pending`, `processing`, `queued`, `in_progress` | No answer yet |
| `valid`, `recovered`, `safe`, `deliverable` | `valid` |
| `invalid`, `reject`, `rejected`, `undeliverable` | `invalid` |
| Anything else (for example `catch-all`) | `unresolved` |

## Tests and fixtures

`tests/providers/test_scrubby.py`. In `tests/providers/fixtures/scrubby/`, only `add_pending.json` and `fetch_pending.json` follow documented shapes; the valid, recovered, invalid and catch-all fixtures are guesses.

## Data sent to the vendor

Email addresses at catch-all domains.
