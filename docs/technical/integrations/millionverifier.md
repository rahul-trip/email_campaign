---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-20 (docs and terms read; not yet checked live)
applies_to: Phase 6
---

# MillionVerifier

| | |
|---|---|
| **Role** | Email verifier, paid by the pack; credits do not expire |
| **Port** | `EmailVerifier` |
| **Adapter** | `outbound/providers/adapters/millionverifier.py::MillionVerifierVerifier` |
| **Registry** | `millionverifier` (as `VERIFIER`, or a backup when its key is set) |
| **Settings** | `MILLIONVERIFIER_API_KEY` |
| **Price** | `millionverifier:verify` 3,900 micro-USD ($39 for 10,000; $89 for 50,000 is $0.00178) |
| **Cache** | `verify`, 90 days |
| **Balance** | `GET /api/v3/credits?api=` (`outbound/providers/balances.py`); the answer's shape is not documented, so an unreadable one is "unknown" |
| **Status** | Built from the vendor's docs on 2026-11-20. **Not checked live** |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `verify(email)` | `GET https://api.millionverifier.com/api/v3/?api=KEY&email=...&timeout=20` | `api` query parameter |

The key is a query parameter, so no URL is ever put in an error message or a log line.

## Mapping

| MillionVerifier `result` | Ours | Charged |
|---|---|---|
| `ok` | `valid` | yes |
| `catch_all` | `catch_all` (goes to the resolver) | no |
| `unknown`, anything unrecognised | `unknown` | no |
| `disposable`, `invalid` | `invalid` | yes |
| `error` | an exception, read from `error` in the body | — |

- **Errors are in the body, not the HTTP status.** `"Apikey not found"` (and any text naming the key or a block) is `ProviderAuthError`; text naming credits is `BudgetExceeded`; anything else is `ProviderError`. Only the bad-key wording is documented; the others are matched loosely and must be confirmed with a live key (the vendor publishes demo keys such as `API_KEY_FOR_ERROR_INSUFFICIENT_CREDITS`).
- **`credits` in the answer is the balance left,** not what the call cost. `billed` therefore comes from the result.
- **A repeat of the same address is charged again** at the vendor, so the meter's cache is what keeps a rerun free.
- `subresult` has no documented list of values and is not read.

## Terms that matter (read 2026-11-20; confirm before relying on them)

- **Use inside our product:** the help centre's *Resellers* article says customers may integrate the API and sell the service as their own. The Terms themselves do not mention resale and forbid transferring credits between accounts, so each workspace is metered in our own AI credits, never in the vendor's.
- **Cold-outreach lists:** the Terms (published 2026-10-19) do not require opt-in, only lawful use, and the vendor may ask for evidence of where a list came from.
- **Catch-all and unknown are free only as goodwill** (Terms §8), which may be withdrawn from an account that verifies "scraped" or "fabricated" data. We verify a few guessed formats for a real, named person ([ADR 0035](../adr/0035-verified-guesses-and-real-time-catch-all-answers.md)); nothing in the Terms names that, but it is the clause nearest to it. Ask the vendor in writing.
- **Operator:** Southern Vector Limited (New Zealand), with a DPA that takes effect on accepting the Terms.

## Tests and fixtures

`tests/providers/test_millionverifier.py` with the verifier contract; fixtures in `tests/providers/fixtures/millionverifier/` (ok, catch_all, unknown, disposable, invalid, error_bad_key, error_no_credits). The `ok` and bad-key shapes are the vendor's own answers to its public test key; the rest are built from the docs.

## Data sent to the vendor

Email addresses.
