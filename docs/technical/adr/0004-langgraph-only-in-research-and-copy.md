---
type: reference
status: accepted
date: 2026-10-16
deciders: "@rahul-trip"
introduced_in: [PLAN.md §3](../../PLAN.md#3-decisions-all-confirmed) decision 3, §4 verdicts 1–3; c3d3228 (#1)
---

# 0004. LangGraph only inside Research and Copy, as stateless subgraphs

## Context

Two stages benefit from a small graph of model calls: research (a supervisor dispatching only the workers a lead needs) and copy (a writer, deterministic assembly and a critic with bounded rewrites). The rest of the pipeline is deterministic and must resume from the database after a crash. LangGraph offers checkpointing, but a second source of truth for progress would compete with lead status.

## Decision

The outer flow is the plain Python runner, routing on company status. LangGraph `StateGraph`s are used only inside `stages/research/` and `stages/copy/`, compiled **without a checkpointer**. The model is never given tools. A stage's graph either completes and returns a `StageResult`, or raises and the lead fails at that stage.

## Consequences

- **Good:** progress lives in one place (status); graphs are pure functions of their input and the (fake) model, so they test deterministically; the model cannot act, only answer.
- **Bad:** a crash inside a graph re-runs the whole graph; vendor lookups come back from cache, but model calls are not cached and are made again; LangGraph is a dependency that needs upgrades (0.3 to 1.x in Phase 3b).
- **Follow-ups:** binding rule 9 in [CLAUDE.md](../../../CLAUDE.md).

## Alternatives considered

| Option | Why not |
|---|---|
| LangGraph for the whole pipeline, with a Postgres checkpointer | Two sources of truth for progress; harder to reason about holds and operator edits |
| An agent framework with tool use | Unbounded calls and cost; actions the operator did not approve |
| Plain functions for research and copy too | The supervisor and the rewrite loop are clearer as small graphs |

## Evidence in the code

- `outbound/stages/research/graph.py` (nodes `pages`, `site`, `legal`, `signals`, `persona`, `fit`; `graph.compile()`); `outbound/stages/copy/graph.py` (`actor`, `assemble`, `critic`; at most 2 rewrites).
- `tests/stages/test_research_graph.py`, `tests/stages/test_copy_graph.py` (scripted model).
