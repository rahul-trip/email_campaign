---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Add a vendor adapter

Add a new finder, verifier, resolver, search or registry vendor without touching any stage ([ADR 0008](../adr/0008-ports-and-adapters.md)). The example is a verifier called `acmeverify`.

1. **Read the vendor's documentation.** Note the endpoints, auth, statuses, billing (what is charged, and when), rate limits, and the error shapes. Save example responses.
2. **Fixtures.** Put the example responses in `tests/providers/fixtures/acmeverify/` as JSON, built from the docs, with no real personal data. Say where they came from in `tests/providers/fixtures/README.md`.
3. **The adapter:** `outbound/providers/adapters/acmeverify.py`.
   - A class with `name = "acmeverify"`, built on `outbound/providers/http.py::HttpClient`. Call `require_api_key` in the constructor, so a missing key fails at start.
   - **Map** the vendor's statuses to the port's enum (`VerificationStatus`: `valid`, `catch_all`, `unknown`, `invalid`). When in doubt, choose `unknown`. Set `billed` from the response if the vendor says so.
   - **Errors:** let `HttpClient` raise. Map a vendor-specific "limit reached" to `BudgetExceeded` (see `tavily.py`). Do not add retries.
   - **Never put the URL or the key in an error message.**
4. **Register it:** add an entry in `outbound/providers/registry.py` (`_VERIFIERS`) with its settings check and constructor.
5. **Settings:** add `acmeverify_api_key: SecretStr = SecretStr("")` to `outbound/config.py::Settings`, and the variable to `.env.example`.
6. **The price:** add `"acmeverify:verify": <micro-USD>` to `outbound/providers/pricing.py::DEFAULT_PRICES`, with a comment saying where the price comes from. **The key must match the operation the meter charges** (see R-04 for what happens when it does not).
7. **Tests:** `tests/providers/test_acmeverify.py`.
   - Subclass the port's contract (`tests/contract/verifier_contract.py::EmailVerifierContract`).
   - Add mapping tests for each fixture.
   - Add a test that a missing key fails.
8. **The live check:** add it to `scripts/live_check.py` if it needs special handling, and run it with your own address.
9. **Docs:**
   - an integration page from the [template](../_templates/integration.md);
   - its row in [integrations](../integrations/README.md) and its price;
   - the [configuration reference](../operations/configuration-reference.md);
   - the sub-processor list in [privacy](../security/privacy-data-processing.md).
10. **Use it:** set `VERIFIER=acmeverify` in `.env` or Doppler. No stage changes.
