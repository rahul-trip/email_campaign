---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Integrations

Every outside system Outbound depends on: what it is for, how it is reached, what it costs, how its answers are cached, and how far it has been proven. The design behind the adapters is in [providers](../lld/providers.md) and [metering](../lld/metering.md).

## Vendors

| Vendor | Role | Port | Registry name | Settings | Cache (TTL) | Live check (2026-10-19) | Page |
|---|---|---|---|---|---|---|---|
| Tavily | Search, page extraction, discovery, LinkedIn-title search | `SearchProvider` | — (always Tavily) | `TAVILY_API_KEY` | `search`, `extract` (30 days) | Works, including `site:` search and extract | [tavily](tavily.md) |
| Hunter | Finder and verifier | `EmailFinder`, `EmailVerifier` | `hunter` | `HUNTER_API_KEY` | `find`, `verify` (90 days) | Verifier works | [hunter](hunter.md) |
| ZeroBounce | Finder and verifier | `EmailFinder`, `EmailVerifier` | `zerobounce` | `ZEROBOUNCE_API_KEY` | `find`, `verify` (90 days) | Verifier works | [zerobounce](zerobounce.md) |
| MyEmailVerifier | Verifier (the default) | `EmailVerifier` | `myemailverifier` | `MYEMAILVERIFIER_API_KEY` | `verify` (90 days) | Works | [myemailverifier](myemailverifier.md) |
| OrbiSearch | Verifier only (no finder API) | `EmailVerifier` | `orbisearch` | `ORBISEARCH_API_KEY` | `verify` (90 days) | Works | [orbisearch](orbisearch.md) |
| Enrichley | Catch-all resolver, answers at once | `CatchAllResolver` | `enrichley` | `ENRICHLEY_API_KEY` | `resolve` (90 days) | Not checked | [enrichley](enrichley.md) |
| Scrubby | Catch-all resolver, asynchronous (24–72 h); the default | `CatchAllResolver` | `scrubby` | `SCRUBBY_API_KEY`, `SCRUBBY_BASE_URL` | `resolve` (90 days) | **Fails**: no answer before the timeout; base URL unconfirmed | [scrubby](scrubby.md) |
| Companies House | UK company register (free) | `CompanyRegistry` | — | `COMPANIES_HOUSE_API_KEY` (optional) | `lookup` (30 days) | Works | [companies-house](companies-house.md) |
| LLM (Anthropic by default; any OpenAI-compatible API) | Research, fit, persona, copy, critic | `LlmClient` | `LLM_PROVIDER` preset | `LLM_PROVIDER`, `LLM_MODEL`, the provider's key, `LLM_BASE_URL` | **Not cached** | Works | [llm](llm.md) |
| IMAP mailbox | Save and delete drafts; read Sent | `Mailbox` | — | `IMAP_*`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, folders | — | Login, save, find and delete a draft all work | [imap-mailbox](imap-mailbox.md) |

## Platforms

| Platform | Role | Page |
|---|---|---|
| Doppler | Secrets for the containers | [platform-doppler](platform-doppler.md) |
| Supabase | Production Postgres | [platform-supabase](platform-supabase.md) |
| GitHub Actions | CI and the deploy workflow | [platform-github-actions](platform-github-actions.md) |

## Prices

The meter records each paid call at these prices: `outbound/providers/pricing.py::DEFAULT_PRICES`, merged with `PROVIDER_PRICES` from settings. They are in micro-USD (1,000,000 = $1). The source of each price is the comment next to it in the code; **check them against your vendor plan before relying on reports**.

| Key | micro-USD | USD | Note |
|---|---|---|---|
| `hunter:find` | 24,500 | $0.0245 | Starter plan, 1 credit per address found; nothing found is not billed |
| `hunter:verify` | 12,250 | $0.01225 | Assumed half a credit; the docs do not state it |
| `zerobounce:find` | 160,000 | $0.16 | 20 credits per address found |
| `zerobounce:verify` | 8,000 | $0.008 | `unknown` results are free |
| `myemailverifier:verify` | 2,500 | $0.0025 | After 100 free requests a day (the free ones are still recorded at this price) |
| `orbisearch:verify` | 200 | $0.0002 | 0.2 credit |
| `enrichley:resolve` | 11,800 | $0.0118 | One credit; not billed when the vendor says so |
| `scrubby:resolve` | unknown (`None`, recorded as 0) | — | Pricing is not public |
| `tavily:search` | 8,000 | $0.008 | One basic search |
| `tavily:extract` | 8,000 | $0.008 | One credit per 5 URLs; charged as one credit per call. Research sends 5 URLs, so this is exact for research |
| `companies_house:lookup` | 0 | free | Rate-limited |
| LLM | `LLM_PRICES` per model, `(input, output)` per million tokens | — | **No defaults: every model call is recorded at $0 unless `LLM_PRICES` is set** ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)) |

The pre-call budget check for a resolver `submit` uses the price of `<resolver>:submit`, which is not in the table, so it checks at $0 ([R-04](../tech-debt-and-risks.md#r-04--p1--cost-the-budget-cap-prices-a-catch-all-submit-at-0)).

## Retries and timeouts

| Path | Timeout | Retries |
|---|---|---|
| Every HTTP vendor (through `HttpClient`) | 30 s | 3 attempts on network errors, 429 (honouring `Retry-After` up to 60 s), 5xx and 202; never on other 4xx |
| LLM | 90 s | As above |
| OrbiSearch | 30 s client; asks the vendor to answer within 25 s | As above |
| IMAP | `IMAP_TIMEOUT_SECONDS` (30 s) | **None** |

## The default chain

`outbound/config.py` (provisional until the Phase 0 bake-off, [R-09](../tech-debt-and-risks.md#r-09--p1--vendors-the-provider-chain-is-unproven-e5-d5)):

```text
FINDER_CHAIN=hunter,zerobounce
VERIFIER=myemailverifier
CATCH_ALL_RESOLVER=scrubby
```

## Choosing and changing the chain

1. Run the bake-off on known contacts: `uv run python -m scripts.bakeoff collect`, then `poll`, then `report`. It calls every configured finder, verifier and resolver, saves the raw answers, and simulates every chain order offline into a CSV ([Phase 0](../../phases/phase-0-fix-and-bakeoff.md)).
2. Set `FINDER_CHAIN`, `VERIFIER` and `CATCH_ALL_RESOLVER` in Doppler (production) or `.env`, then restart the worker.
3. Check the vendor with `uv run python -m scripts.live_check` (on your own address; finders only with `--finders`).
4. Record the result on the vendor's page and in the phase document.

A new vendor is added with [add a vendor adapter](../guides/add-a-vendor-adapter.md).

## Personal data sent out

Each vendor page lists what leaves the system in each call. In summary:

- **Finders** receive a person's first and last name and the company domain.
- **Verifiers and resolvers** receive email addresses.
- **Tavily** receives company names, domains, job titles and the company's page URLs.
- **The LLM provider** receives page text, people's names and titles, notes, and drafts.
- **Companies House** receives company names.

Every vendor is a sub-processor; see [privacy](../security/privacy-data-processing.md).

## How to refresh this page

```bash
sed -n '/DEFAULT_PRICES/,/^}/p' outbound/providers/pricing.py
grep -n "TTL = " outbound/metering/metered.py
grep -n "finder_chain\|verifier\b\|catch_all_resolver" outbound/config.py
grep -n "BASE_URL =" outbound/providers/adapters/*.py
```
