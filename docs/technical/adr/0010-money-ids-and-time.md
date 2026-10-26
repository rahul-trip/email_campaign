---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [CLAUDE.md](../../../CLAUDE.md) value conventions; c3d3228 (#1)
---

# 0010. Integer micro-USD for money, UUIDv7 strings for ids, UTC for time

## Context

Costs are fractions of a cent per call and are summed into budgets and reports. Ids are created in the application (before rows exist) and must sort by creation. Leads span time zones, and both databases must store time the same way.

## Decision

Money is an integer number of micro-dollars everywhere, in code and columns; floats are refused at the boundary. Ids are UUIDv7 strings, created by `outbound/domain/ids.py::new_id`. Every timestamp is timezone-aware UTC; the column type refuses naive datetimes.

## Consequences

- **Good:** exact sums; time-ordered ids that are safe to create before insert and index well; no time-zone bugs between SQLite and Postgres.
- **Bad:** micro-USD must be formatted for display; UUIDs are long in URLs and logs.
- **Follow-ups:** none.

## Alternatives considered

| Option | Why not |
|---|---|
| Decimal or float dollars | Floats drift; decimals differ between the two databases |
| Auto-increment integer ids | Not known before insert; reveal volume; clash across workspaces |
| Local time with a zone column | Two values to keep consistent; easy to get wrong |

## Evidence in the code

- `outbound/domain/money.py` (`usd_to_micro` refuses floats), `outbound/domain/ids.py`, `outbound/db/types.py::UtcDateTime`.
