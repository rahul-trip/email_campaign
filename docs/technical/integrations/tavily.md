---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Tavily

| | |
|---|---|
| **Role** | Web search and page extraction: research pages, signals, discovery, the LinkedIn-title people search, name-to-domain resolution at intake |
| **Port** | `outbound/providers/ports.py::SearchProvider` |
| **Adapter** | `outbound/providers/adapters/tavily.py::TavilySearch` |
| **Registry** | Always Tavily (`outbound/providers/registry.py::build_search`) |
| **Settings** | `TAVILY_API_KEY` (required for the worker; without it the API's intake leaves name-only rows `pending`) |
| **Price** | `tavily:search` and `tavily:extract`, 8,000 micro-USD each ([prices](README.md#prices)) |
| **Cache** | `search` on `{query, max_results}`; `extract` on the sorted URLs; 30 days |
| **Status** | Live-checked 2026-10-19: search, `site:` search and extract work |

## Endpoints used

| Operation | Method and path | Auth | Timeout and retry |
|---|---|---|---|
| `search(query, max_results)` | `POST https://api.tavily.com/search` with `{query, max_results (1–20), search_depth: "basic"}` | `Authorization: Bearer <key>` | `HttpClient`: 30 s, 3 attempts |
| `extract(urls)` | `POST https://api.tavily.com/extract` with `{urls (≤ 20 per request), format: "text"}` | Bearer | As above; more than 20 URLs are split into batches |

## Mapping

| Tavily field | Ours |
|---|---|
| `results[].url`, `title`, `content`, `score` | `SearchHit(url, title, snippet, score)`; results without a URL are dropped |
| `results[].url`, `raw_content` | `PageText(url, text)`; pages with no content are dropped |

## Errors

| Tavily answer | Raised as | Retried |
|---|---|---|
| 432 or 433 (plan or pay-as-you-go limit) | `BudgetExceeded` | No |
| 401, 403 | `ProviderAuthError` | No |
| 429, 5xx, network | `ProviderError` (retryable) | Yes |
| A body that is not a JSON object | `ProviderError` | No |

## Limits and quirks

- One basic search costs 1 credit. Extraction costs 1 credit per 5 URLs, but the meter charges one credit per call, which is exact for research's 5-URL extract.
- Tavily honours `site:` in a query (checked live), which the people search relies on.
- Rate limits are not documented here; check the Tavily dashboard.

## Tests and fixtures

`tests/providers/test_tavily.py` (Bearer key, `max_results` capped, plan limits as `BudgetExceeded`, mapping), and `tests/contract/search_contract.py`. Fixtures `tests/providers/fixtures/tavily/search.json` and `extract.json` are built from the documentation.

## Data sent to the vendor

Company names and domains, the company's page URLs, job titles (people search), and the campaign's ideal-customer text (discovery).
