---
type: reference
status: accepted
date: 2026-10-21
deciders: "@rahul-trip"
introduced_in: 98805ad (migration 0003)
---

# 0023. Discovery stores websites, not names; searched people are confirmed by their employer

## Context

A discovery run named companies after search-result headlines ("6 Grid Trends to Watch in 2026"), and the LinkedIn search then accepted anyone sharing one word with that headline. Six people at other companies were attached to three leads.

## Decision

Discovery stores only the website and the page it was found on, and skips articles and documents. Research's site worker runs first and returns the company's own name, which the other workers use. A searched person is saved as a `candidate` only when their profile's employer is the company (its whole name or website name); a person merely mentioned with it is saved as `unconfirmed` (a new contact status) and is not worked on until the operator confirms them; anyone else is dropped.

## Consequences

- **Good:** names come from the company itself; wrong people are not written to; uncertain matches are visible rather than silently used.
- **Bad:** more leads need an operator's confirmation; confirming a person is a skip that approval must acknowledge.
- **Follow-ups:** a data fix for the affected run (`scripts/fix_discovery_data.py`).

## Alternatives considered

| Option | Why not |
|---|---|
| Fuzzy matching on name tokens | One shared word matched unrelated people |
| Drop every unconfirmed person | Loses real people that only the operator can confirm |

## Evidence in the code

- `outbound/domain/names.py` (`employer_matches`, `mentions_company`, `read_profile_title`); `outbound/stages/research/graph.py::search_people`; `outbound/services/intake.py::discover_rows`; migration `0003_unconfirmed_contacts`.
- `tests/stages/test_research_graph.py`, `tests/domain/test_basics.py`.
