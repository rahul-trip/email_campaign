---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: YYYY-MM-DD (<short SHA>)
applies_to: Phase N
---

<!-- Relative links in this template are written for a page in docs/technical/integrations/. -->
# <Vendor>

| | |
|---|---|
| **Role** | finder / verifier / catch-all resolver / search / LLM / company registry / mailbox |
| **Port** | `outbound/providers/ports.py::<Protocol>` |
| **Adapter** | `outbound/providers/adapters/<file>.py::<Class>` |
| **Registry name** | `<name>` as used in `FINDER_CHAIN`, `VERIFIER` or `CATCH_ALL_RESOLVER` |
| **Settings** | `<VENDOR>_API_KEY`, … (see the [configuration reference](../operations/configuration-reference.md)) |
| **Price** | `<vendor>:<operation>` = N micro-USD (see [pricing](README.md#prices)) |
| **Cache** | operation, key, TTL |
| **Status** | live-checked on YYYY-MM-DD / not yet live-checked / failing (register entry) |

## Endpoints used

| Operation | Method and path | Auth | Timeout and retry |
|---|---|---|---|

## Mapping

How the vendor's answer becomes the port's model: each vendor status → our enum, and what `billed` means.

| Vendor field or status | Our value |
|---|---|

## Errors

| Vendor response | Raised as | Retried? |
|---|---|---|

## Limits and quirks

Rate limits, credits, known oddities, and what the docs leave unclear.

## Tests and fixtures

`tests/providers/test_<vendor>.py`, `tests/providers/fixtures/<vendor>/`, and where the fixtures came from.

## Data sent to the vendor

The personal data that leaves the system in each call (for the [privacy record](../security/privacy-data-processing.md)).
