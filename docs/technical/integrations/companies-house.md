---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Companies House

| | |
|---|---|
| **Role** | UK company register: is this name a registered company (a corporate subscriber under PECR)? |
| **Port** | `CompanyRegistry` |
| **Adapter** | `outbound/providers/adapters/companies_house.py::CompaniesHouse` |
| **Registry** | `build_company_registry`; optional |
| **Settings** | `COMPANIES_HOUSE_API_KEY` (free; without it UK leads rely on site markers and usually stay `entity_unknown`) |
| **Price** | `companies_house:lookup` 0 |
| **Cache** | `lookup` on `{name, max_results}`, 30 days |
| **Status** | Live-checked 2026-10-19 (the key had been stored under the wrong variable name, `COMPANIES_HOUSE`) |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `search(company_name, max_results)` | `GET https://api.company-information.service.gov.uk/search/companies?q&items_per_page (≤ 20)` | HTTP Basic: the key as user name, empty password |

## Mapping

`items[]` with a `company_number` become `RegistryEntry(name=title, number, status=company_status, company_type, address=address_snippet)`. The research stage picks the best match by name (`outbound/stages/research/facts.py::best_registry_match`), then classifies the legal entity together with the site's own markers (`classify_legal_entity`).

## Limits

Free; 600 requests per 5 minutes.

## Tests and fixtures

`tests/providers/test_companies_house.py`; fixture `tests/providers/fixtures/companies_house/search.json`.

## Data sent to the vendor

Company names (public register data).
