---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Hunter

| | |
|---|---|
| **Role** | Email finder and verifier |
| **Port** | `EmailFinder`, `EmailVerifier` |
| **Adapter** | `outbound/providers/adapters/hunter.py::HunterFinder`, `HunterVerifier` |
| **Registry** | `hunter` (in `FINDER_CHAIN`, or as `VERIFIER`) |
| **Settings** | `HUNTER_API_KEY` |
| **Price** | `hunter:find` 24,500; `hunter:verify` 12,250 (assumed) micro-USD |
| **Cache** | `find` on `{person, domain}`; `verify` on `{email}`; 90 days |
| **Status** | Verifier live-checked 2026-10-19 (valid for the operator's address); finder not yet checked live |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `find(person, domain)` | `GET https://api.hunter.io/v2/email-finder?domain&first_name&last_name` | `X-API-KEY` header |
| `verify(email)` | `GET https://api.hunter.io/v2/email-verifier?email` | `X-API-KEY` |

## Mapping

| Hunter | Ours |
|---|---|
| Finder `data.email`, `data.score` (0–100), `data.verification.status` | `FinderResult(email, confidence = score / 100, raw_status)`; `billed` only when an address came back |
| Verifier `valid` | `valid` |
| `invalid`, `disposable` | `invalid` |
| `accept_all` | `catch_all` |
| `webmail`, `unknown`, anything else | `unknown` (a free-mail address is not a business contact) |
| HTTP **451** (the person asked Hunter to stop processing their data) | Finder: no address, not billed. Verifier: `invalid`, not billed (`raw_status` `claimed_email`) |
| HTTP 202 (verification still running) | Retried by `HttpClient` |

## Errors

401 and 403 raise `ProviderAuthError`; 429, 5xx and network errors are retried; other 4xx raise `ProviderError`.

## Tests and fixtures

`tests/providers/test_hunter.py` runs the shared finder and verifier contracts. Fixtures in `tests/providers/fixtures/hunter/`: finder found and not found; verifier valid, invalid, accept_all, disposable, webmail, unknown.

## Data sent to the vendor

A person's first and last name and the company domain (finder); an email address (verifier).
