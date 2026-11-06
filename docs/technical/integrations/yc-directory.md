---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-06 (phase-6/discovery-sources)
applies_to: Phase 6 follow-up (discovery)
---

# Y Combinator directory

| | |
|---|---|
| **Role** | A start-up directory for discovery: active YC companies whose description uses the brief's words |
| **Port** | `LeadSource` |
| **Adapter** | `outbound/providers/adapters/yc_directory.py::YcDirectory` |
| **Registry** | `build_company_sources`; always on, no key |
| **Settings** | None |
| **Price** | `yc_directory:find` 0 |
| **Cache** | The whole directory is kept in memory for a day; `find` on the query and limit, 30 days, in the ledger |
| **Status** | Not live-checked. The fixture is built from the mirror's documented fields ([R-29](../tech-debt-and-risks.md)) |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| The whole directory | `GET https://yc-oss.github.io/api/companies/all.json` | None |

## Mapping

Each company with `status` *Active* or *Public* is a candidate. It is kept when:

- every word of a brief keyword appears (as a word, not inside another: *ai* is not in *maintain*) in its `one_liner`, `long_description`, `subindustry`, `tags` or `industries` (a match of the whole phrase counts double);
- a brief region appears as whole words in `all_locations` or `regions`, or by a common name (*UK* → *United Kingdom*, *US* → *United States*, *EU* → *Europe*), so *US* never matches *Russia*;
- its batch year (`Winter 2022` or `W22`) is not before the brief's *founded after*.

The best matches come first. A match becomes `CompanyMention(name, domain=registrable_domain(website), description=one_liner + long_description, tags, country=regions[0], founded=batch year, size=team_size, stage, source="yc_directory", source_url=url, evidence="Y Combinator <batch>: <one_liner>")`.

## When it fails

A failed download is a `ProviderError`. Discovery logs `discovery_source_failed` with `source=yc_directory` and carries on with the other sources.
