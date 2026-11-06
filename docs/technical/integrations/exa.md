---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-06 (phase-6/discovery-more-sources)
applies_to: Phase 6 follow-up (discovery)
---

# Exa

| | |
|---|---|
| **Role** | A discovery source: company home pages that match the brief's description, and lookalikes of example customers |
| **Port** | `LeadSource` |
| **Adapter** | `outbound/providers/adapters/exa.py::ExaSearch` |
| **Registry** | `build_company_sources`; only when the key is set |
| **Settings** | `EXA_API_KEY` (optional), or the `exa` vendor key in the admin console |
| **Price** | `exa:find` 90,000 micro-USD: one search plus up to two lookalike requests, each $0.005 for up to 25 results plus $0.001 a page for its text |
| **Cache** | `find` on the query and limit, 30 days, in the ledger |
| **Status** | Not live-checked. The fixtures are built from Exa's documented responses ([R-30](../tech-debt-and-risks.md)) |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| Companies the brief describes | `POST https://api.exa.ai/search` with `query`, `type: auto`, `category: company`, `numResults` (≤ 25), `contents.text.maxCharacters` 600 | `x-api-key` header |
| Lookalikes of an example customer | `POST https://api.exa.ai/findSimilar` with `url`, `numResults`, `excludeSourceDomain`, `category: company`, the same `contents` | `x-api-key` header |

## What it is asked

- **The search** is the brief's summary, or, without one, its first keywords, first segment and regions (`grid forecasting companies in UK`).
- **Lookalikes** come from the first two example customers given as websites: the brief's `seed_companies` that look like a domain, then the campaign's leads that passed the fit gate, best fit first (`CompanyRepository.qualified_domains`, at most 3). A bare company name is not looked up.

## Mapping

Each result with a URL becomes one `CompanyMention` per registrable domain (the first wins):

- `name` is the page title up to its first separator (`Gridcast | Load forecasting` → `Gridcast`); research replaces it with the site's own name;
- `domain` is the registrable domain of `url`; `description` is the text extract;
- `evidence` is `Exa: <text>` or `Exa, like <example>: <text>`.

## When it fails

Any error after the shared client's retries is a `ProviderError`; discovery logs `discovery_source_failed` with `source=exa` and carries on with the other sources.

## Tests and fixtures

`tests/providers/test_exa.py`; fixtures `tests/providers/fixtures/exa/search.json` and `find_similar.json`.

## Data sent to the vendor

The brief's summary or words, and the websites of example customers and qualified leads (public company websites; no personal data).
