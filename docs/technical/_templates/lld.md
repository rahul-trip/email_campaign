---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: YYYY-MM-DD (<short SHA>)
applies_to: Phase N
---

# <Module name>

**Code:** `outbound/<package>/` · **Layer:** <domain | db | providers | metering | stages | runner | services | pipeline | api/cli/worker> · **Tests:** `tests/<…>`

## Purpose

One paragraph: what this module is for, and the one reason it exists as a separate module.

## Responsibilities

- What it does.

**Not its job** (and where that lives instead):

- …

## Public interface

The names other modules use. Signatures are summarised; the code is the reference.

| Symbol | Kind | What it does |
|---|---|---|
| `path::Name` | class / function / protocol | … |

## Collaborators

| Depends on | For | Used by | For |
|---|---|---|---|
| … | … | … | … |

## Data it owns

Tables, columns or JSON keys this module writes, with links to [schema.md](../data/schema.md). Write "none" if it owns none.

## How it works

The main control flow, with one Mermaid sequence or flowchart where it helps. Explain ordering that matters and why.

## Invariants

The rules that always hold after this module runs (for example "a ledger row exists for every paid call, even a failed one").

## Errors, retries and failure behaviour

| Failure | What happens | Who sees it |
|---|---|---|
| … | … | … |

## Transactions and concurrency

Which transactions it opens, how long they last, what it locks or version-checks, and what happens on a conflict.

## Configuration

Settings it reads, linking each to [configuration-reference.md](../operations/configuration-reference.md).

## Observability

The log events it emits, linking to [observability.md](../operations/observability.md), and the `events` rows it writes.

## Security and privacy

Untrusted input it handles, personal data it touches, and secrets it uses.

## Tests

Which test files prove what. Name the important cases.

## Known limitations

One line per item, each linking its [register](../tech-debt-and-risks.md) entry.

## Extending it

The safe way to add to this module (link to the matching [guide](../guides/) if there is one).

## Planned

Links to the phase documents that change this module. Do not describe the future design here.
