"""agent/graph/state.py — AgentState TypedDict for the LangGraph StateGraph.

Design:
    - config / run_id / companies / leads / appended_row_count /
      drafts_start_row / draft_result are last-writer-wins (each set by exactly one node).
    - step_log and errors use operator.add so multiple nodes can append without
      stomping each other's records.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from agent.config.models import AgentConfig
from agent.domain.models import Company, Lead


class AgentState(TypedDict, total=False):
    """Shared state threaded through every LangGraph node."""

    # ---- inputs (set once in main.py, never mutated by nodes) --------
    config: AgentConfig
    run_id: str

    # ---- working data (last-writer-wins; each key set by one node) ----
    companies: list[Company]
    leads: list[Lead]
    appended_row_count: int
    drafts_start_row: int          # first workbook row appended this run
    draft_result: dict

    # ---- observability (reducer: nodes append, never overwrite) -------
    step_log: Annotated[list, operator.add]   # list[StepRecord]
    errors: Annotated[list, operator.add]     # list[str]
