---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# MyEmailVerifier

| | |
|---|---|
| **Role** | Email verifier (the default `VERIFIER`) |
| **Port** | `EmailVerifier` |
| **Adapter** | `outbound/providers/adapters/myemailverifier.py::MyEmailVerifierVerifier` |
| **Registry** | `myemailverifier` |
| **Settings** | `MYEMAILVERIFIER_API_KEY` |
| **Price** | `myemailverifier:verify` 2,500 micro-USD (after 100 free requests a day; the meter records every call at this price) |
| **Cache** | `verify`, 90 days |
| **Status** | Live-checked 2026-10-19 |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `verify(email)` | `GET https://api.myemailverifier.com/api/validate_single.php?apikey&email` | `apikey` query parameter |

## Mapping

Checked in this order (`MyEmailVerifierVerifier._classify`):

| MyEmailVerifier | Ours |
|---|---|
| `Status` invalid, spam trap; or `Disposable_Domain` true | `invalid` |
| `Status` catch-all; or `catch_all` true | `catch_all` |
| `Greylisted` true | `unknown` |
| `Status` valid | `valid` |
| Anything else | `unknown` |

`billed` is always true (the model's default).

## Tests and fixtures

`tests/providers/test_myemailverifier.py` with the verifier contract; fixtures in `tests/providers/fixtures/myemailverifier/` (valid, invalid, catch-all, disposable, greylisted, unrecognised).

## Data sent to the vendor

Email addresses.
