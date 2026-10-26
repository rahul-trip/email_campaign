---
type: reference
status: accepted
date: 2026-10-26
deciders: "@rahul-trip"
introduced_in: 8129c78
---

# 0029. A cross-workspace verified lead directory, with attribution structurally absent rather than filtered out

## Context

Two customers' waterfalls independently pay to find and verify the same address whenever they happen to target the same company's same decision-maker — the platform has many customers now, so this duplication is no longer rare. Sharing a verified fact between customers saves real money (a paid finder lookup each time it's avoided), but doing so crosses a boundary every other part of the Phase 6a redesign exists to hold firm: one workspace's data reaching another's.

## Decision

A platform-level directory of verified email addresses, served as the free first link of every workspace's email waterfall (`DirectoryFinder`, `billed=False`), re-verified on every hit before use. An address becomes contributable only once a workspace's own run confirms it to `VALID` or `CATCH_ALL_RESOLVED` — an unverified or invalid finding teaches the directory nothing. Critically, every shape the directory can ever return (`DirectoryHit`, `DirectoryBadge`) is constructed with no field capable of carrying a contributor's identity: `month()` discards the day a fact was verified (not just the workspace id), so even timing cannot be correlated back to a specific customer's run. This is a structural choice, not a redaction step applied when serving — the contributing workspace is never written into the shared fact's row at all. A dispute (`report()`) moves the shared fact out of circulation for everyone pending platform review, and simultaneously invalidates the address in the reporting workspace's own data, independent of that review's outcome. An entitlement feature (`directory_bypass`) lets an admin grant a specific customer the ability to skip the directory and go straight to the paid vendors.

## Consequences

- **Good:** real savings on duplicate paid lookups, provable and reasoned about with the same rigour as any other tenant-isolation decision in this phase — the directory is the *one* deliberate, bounded exception to "no cross-tenant data," rather than an accidental one. A customer disputing a bad address is protected immediately, not after a review queue clears.
- **Bad:** a disputed fact is unavailable to everyone until a platform admin reviews it, with no SLA defined yet on how long that takes — a false dispute (or a legitimate one that takes a while to review) costs every customer the saving, not just the one who reported it.
- **Follow-ups:** the directory's reported "savings" figure is an estimate (the cost of the first chain finder), not a measured counterfactual against what a later, cheaper finder in the chain might have found anyway.

## Alternatives considered

| Option | Why not |
|---|---|
| No cross-workspace sharing at all | Leaves real, recurring duplicate spend on the table for a fact that is, once verified, a business email address rather than sensitive personal correspondence |
| Store the contributing workspace, filter it out at serving time | A field that exists can be queried directly against the database by anyone with sufficient access (a bug, a future report, a platform admin's own curiosity); not writing it at all removes that risk category entirely |
| Serve the exact verification date | A precise date is one more correlatable signal than a month is; the month was judged a small enough grain to be useless for inferring another customer's run timing while still being informative ("this is fresh" vs. "this is old") |

## Evidence in the code

- `outbound/domain/directory.py` (`person_key`, `servable`, `CONTRIBUTABLE`, `month`, `DirectoryHit`).
- `outbound/services/directory.py::LeadDirectory`, `DirectoryService`.
- `outbound/stages/email/directory.py::DirectoryFinder`.
- `tests/domain/test_directory.py`, `tests/services/test_directory.py`, `tests/stages/test_directory_finder.py`.
