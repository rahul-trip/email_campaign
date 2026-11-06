---
type: reference
status: accepted
date: 2026-11-06
deciders: "@rahul-trip"
introduced_in: phase-6/discovery-sources
---

# 0031. Discovery looks in several sources, and screens every company against the brief before it becomes a lead

## Context

Discovery used to make one kind of web search ("companies offering products or services for: <ideal customer>"). It turned every new domain in the results into a lead, which charged a discovery credit, and judged fit only after full research (4–6 search credits and 2–5 model calls per lead). The phrasing found vendors that *serve* the ideal customer, often competitors. Most discovered leads were then disqualified at the gate, after the money was spent, and what was searched for, and why, was hard to see.

## Decision

- **A structured brief.** Every campaign has an editable ideal-customer brief (`campaigns.icp_brief`, `outbound/domain/brief.py`). Discovery works from it.
- **Several sources behind one port.** A run asks every source that suits the brief (`outbound/domain/discovery.py::plan_sources`), through the `LeadSource` port (`outbound/providers/ports.py`), metered by `MeteredLeadSource`:
  - **Start-up directories:** the Y Combinator directory, when the brief is after start-ups.
  - **Pages that list many companies:** rankings, funding round-ups, cohorts and member lists. A model plans the searches from the brief and reads each page for the companies it describes (`services/discovery.py::ArticleSource`).
- **Merge, screen, then add.** Mentions are merged by website, else by name without its legal suffix, and the number of sources counts as corroboration. One model call per batch of 15 then screens them against the brief. Only fits are added as leads (charging the credit), best first; a company without a website gets one search for it.
- **Every company is remembered.** Each one is kept with its verdict (`discovery_candidates`, migration 0019), so none is screened twice, a fit over the run's limit goes first next time, and a person can promote one the screening left out.

## Consequences

- **Good:**
  - Credits and research go only to companies that fit the brief.
  - Structured directories bring clean descriptions at no cost.
  - What was searched, which pages were read and why each company was or was not added are all visible on the run's page.
  - Adding a source (Companies House advanced search, a lookalike search) means one more adapter and one entry in `plan_sources`.
- **Bad:**
  - A run now spends model calls before adding anything: one to plan, one per page read, and one per batch of 15 companies screened.
  - The Y Combinator data comes from a public mirror (`yc-oss`), not from YC itself. Its freshness and terms need checking before relying on it, and it is recorded in the risk register.
  - Screening judges from short descriptions, so a good company can be left out. The run's page and **Make a lead** are the remedy.
- **Follow-ups:**
  - Companies House advanced search for UK briefs.
  - A lookalike source (Exa) from example customers.
  - Weighting sources by how many of their leads qualify.

## Alternatives considered

| Option | Why not |
|---|---|
| Fetch each search hit's homepage and judge it before adding | The operator ruled it out: too costly per candidate, and a search hit is a poor way to find companies in the first place |
| Keep one search but screen its hits | Still finds vendors and articles rather than customers. The phrasing was the problem, not only the missing screen |
| Paid company databases (Crunchbase, PDL) first | Cost and terms; added later, behind a key, only if free sources prove thin |

## Relation to earlier decisions

[ADR 0023](0023-discovery-stores-websites-unconfirmed-people.md) still holds: a search result's title is never a company's name. Names now come from the source (a directory entry, or the model reading a list page), and research replaces them with the name on the company's own site.

## Evidence in the code

- `outbound/domain/brief.py`, `outbound/domain/discovery.py` (`plan_sources`, `article_queries`, `name_key`).
- `outbound/services/discovery.py` (`Discoverer`, `ArticleSource`, `merge`, `screen`), `outbound/services/candidates.py`.
- `outbound/providers/adapters/yc_directory.py`, `outbound/metering/metered.py::MeteredLeadSource`.
- `tests/db/test_discovery.py`, `tests/db/test_discovery_planning.py`, `tests/db/test_candidates.py`, `tests/providers/test_yc_directory.py`, `tests/api/test_candidates.py`.
