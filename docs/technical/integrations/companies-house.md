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
| **Role** | UK company register: is this name a registered company (a corporate subscriber under PECR)? Also a discovery source: active UK companies by industry code |
| **Port** | `CompanyRegistry`, and `LeadSource` for discovery |
| **Adapter** | `outbound/providers/adapters/companies_house.py::CompaniesHouse` |
| **Registry** | `build_company_registry` and `build_company_sources`; optional |
| **Settings** | `COMPANIES_HOUSE_API_KEY` (free; without it UK leads rely on site markers and usually stay `entity_unknown`) |
| **Price** | `companies_house:lookup` 0, `companies_house:find` 0 |
| **Cache** | `lookup` on `{name, max_results}`, 30 days |
| **Status** | Live-checked 2026-10-19 (the key had been stored under the wrong variable name, `COMPANIES_HOUSE`) |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `search(company_name, max_results)` | `GET https://api.company-information.service.gov.uk/search/companies?q&items_per_page (≤ 20)` | HTTP Basic: the key as user name, empty password |
| `find(query, limit)` | `GET https://api.company-information.service.gov.uk/advanced-search/companies?sic_codes&company_status=active&company_type=ltd,plc,llp&incorporated_from&size (≤ 100)` | The same |

## Mapping

`items[]` with a `company_number` become `RegistryEntry(name=title, number, status=company_status, company_type, address=address_snippet)`. The research stage picks the best match by name (`outbound/stages/research/facts.py::best_registry_match`), then classifies the legal entity together with the site's own markers (`classify_legal_entity`).

**Discovery** (`find`) is used for a brief whose regions include the UK and that has industry (SIC) codes (`outbound/domain/discovery.py::plan_sources`). Without codes nothing is asked: the register cannot search by description. Only companies, plcs and LLPs are asked for, since PECR lets us email those. Each item with a name and number becomes `CompanyMention(name (title case when all capitals), domain=None, description and evidence = type, town, incorporation date and SIC codes, tags=SIC codes, country="GB", founded=year of creation, source="companies_house", source_url=<the register's page>)`. The register has no websites, so a fit is added only once `DomainResolver` confirms one (one search each, for the best fits only); otherwise it is kept as *unresolved*.

## Limits

Free; 600 requests per 5 minutes.

## Tests and fixtures

`tests/providers/test_companies_house.py`; fixtures `tests/providers/fixtures/companies_house/search.json` and `advanced_search.json` (built from the advanced-search reference).

## Data sent to the vendor

Company names, and industry codes and a year for discovery (public register data).
