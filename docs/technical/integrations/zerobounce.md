---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# ZeroBounce

| | |
|---|---|
| **Role** | Email finder (`guessformat`) and verifier |
| **Port** | `EmailFinder`, `EmailVerifier` |
| **Adapter** | `outbound/providers/adapters/zerobounce.py::ZeroBounceFinder`, `ZeroBounceVerifier` |
| **Registry** | `zerobounce` |
| **Settings** | `ZEROBOUNCE_API_KEY` |
| **Price** | `zerobounce:find` 160,000; `zerobounce:verify` 8,000 micro-USD |
| **Cache** | `find` and `verify`, 90 days |
| **Status** | Verifier live-checked 2026-10-19; finder not yet checked live |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `find(person, domain)` | `GET https://api.zerobounce.net/v2/guessformat?domain&first_name&last_name&api_key` | `api_key` query parameter |
| `verify(email)` | `GET https://api.zerobounce.net/v2/validate?email&api_key` | `api_key` query parameter |

The key travels in the query string. That is why error messages and logs never include URLs, and why httpx's logs are silenced ([logging](../lld/logging.md)).

## Mapping

| ZeroBounce | Ours |
|---|---|
| Finder `email`, `email_confidence` HIGH, MEDIUM, LOW | `FinderResult(email, confidence 0.9 / 0.6 / 0.3)`; billed only when an address came back |
| `valid` | `valid` |
| `catch-all` | `catch_all` |
| `invalid`, `spamtrap`, `abuse`, `do_not_mail` | `invalid` |
| `unknown`, anything else | `unknown`, **not billed** |
| A JSON `error` field mentioning "key" or "credit" | `ProviderAuthError` (not retried) |
| Any other `error` field | `ProviderError` |

## Tests and fixtures

`tests/providers/test_zerobounce.py` with the shared contracts; fixtures in `tests/providers/fixtures/zerobounce/` (finder found and unknown; validate valid, catch-all, invalid, spamtrap, do_not_mail, unknown; an invalid-key error).

## Data sent to the vendor

A person's first and last name and the company domain; email addresses.
