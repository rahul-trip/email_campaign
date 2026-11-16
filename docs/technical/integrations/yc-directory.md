---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-16 (phase-6/directory-sources)
applies_to: Phase 6 follow-up (discovery)
---

# Y Combinator directory

| | |
|---|---|
| **Role** | A start-up directory for discovery: active YC companies about the brief's words, not seen on an earlier run |
| **Port** | `LeadSource` |
| **Adapter** | `outbound/providers/adapters/yc_directory.py::YcDirectory` |
| **Registry** | `build_company_sources`; always on, no key |
| **Settings** | None |
| **Price** | `yc_directory:find` 0 |
| **Cache** | The whole directory is kept in memory for a day; `find` on the query (its known websites included, so each run asks a new question) and limit, 30 days, in the ledger |
| **Status** | Not live-checked. The fixture is built from the mirror's documented fields ([R-29](../tech-debt-and-risks.md)) |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| The whole directory | `GET https://yc-oss.github.io/api/companies/all.json` | None |

## Mapping

Each company with `status` *Active* or *Public* is a candidate. It is kept when:

- it is about the query's words, taken one by one and compared by stem (*utilities* finds *utility*, *forecasting* finds *forecast*; *ai* is not in *maintain*). A word in `industries`, `subindustry` or `tags` counts 3 and one in `one_liner` or `long_description` counts 1. A company is kept on one label hit, or on two different words in its prose (one, when only one was asked), so "the power of biotech" is not an energy company. The words are the brief's keywords, or without them the telling words of its segments and summary (`domain/discovery.py::search_terms`; *start-ups* and *platforms* are dropped). Before 2026-11-16 the whole keyword or every word of it had to appear, so a brief without keywords matched nothing in 8 production runs ([R-36](../tech-debt-and-risks.md));
- its website is not in the query's `exclude_domains` (the workspace's leads and every candidate found before), applied before the limit, so each run brings companies not seen before;
- a brief region appears as whole words in `all_locations` or `regions`, or by a common name (*UK* → *United Kingdom*, *US* → *United States*, *EU* → *Europe*), so *US* never matches *Russia*;
- its batch year (`Winter 2022` or `W22`) is not before the brief's *founded after*.

The best matches come first, the newest batch first among equals. A match becomes `CompanyMention(name, domain=registrable_domain(website), description=one_liner + long_description, tags, country=regions[0], founded=batch year, size=team_size, stage, source="yc_directory", source_url=url, evidence="Y Combinator <batch>: <one_liner>. <team size> people; <stage> stage; <locations>; <tags>; hiring")`. The evidence line is what screening reads about size and place.

## When it fails

A failed download is a `ProviderError`. Discovery logs `discovery_source_failed` with `source=yc_directory` and carries on with the other sources.
