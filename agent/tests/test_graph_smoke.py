"""agent/tests/test_graph_smoke.py — End-to-end smoke test with all-fake providers.

Builds the full LangGraph pipeline, invokes it with fake providers and a
tmp workbook, and asserts:
    - Rows were appended to the workbook.
    - Every stage produced an "ok" StepRecord in step_log.
    - No errors were recorded.
    - No network calls were made (fakes have no HTTP dependencies).
"""

from __future__ import annotations

import openpyxl
import pytest

from agent.domain.models import COLUMN_ORDER
from agent.graph.build import build_graph
from agent.graph.state import AgentState
from agent.persistence.lead_repository import XlsxLeadRepository
import logging


_LOG = logging.getLogger("agent")
_EXPECTED_STAGES = [
    "discover_companies",
    "resolve_contacts",
    "find_emails",
    "verify_emails",
    "generate_copy",
    "persist_rows",
    "sync_drafts",
]


def test_graph_smoke_full_run(fake_bundle, test_config, repo, tmp_xlsx):
    """Full graph run with fakes: rows appended, all stages OK, no errors."""
    graph = build_graph(fake_bundle, repo, test_config, _LOG)

    initial: AgentState = {
        "config": test_config,
        "run_id": "test_run_001",
        "companies": [],
        "leads": [],
        "appended_row_count": 0,
        "draft_result": {},
        "step_log": [],
        "errors": [],
    }

    final = graph.invoke(initial)

    # --- Step log: all stages present and OK ---
    step_names = [r.step for r in final.get("step_log", [])]
    for stage in _EXPECTED_STAGES:
        assert stage in step_names, f"Missing step_log entry for {stage!r}"

    ok_statuses = {r.step: r.status for r in final.get("step_log", [])}
    for stage in _EXPECTED_STAGES:
        assert ok_statuses.get(stage) == "ok", (
            f"Stage {stage!r} has status {ok_statuses.get(stage)!r}, expected 'ok'"
        )

    # --- Rows actually appended ---
    assert final.get("appended_row_count", 0) > 0, "No rows were appended"

    # --- Workbook grew ---
    wb = openpyxl.load_workbook(str(tmp_xlsx), read_only=True, data_only=True)
    all_rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    # header + 1 seed + N appended
    assert len(all_rows) >= 3, "Workbook should have at least 3 rows after run"

    # --- No errors ---
    assert final.get("errors", []) == [], f"Unexpected errors: {final.get('errors')}"


def test_graph_ends_early_with_no_companies(fake_bundle, test_config, repo):
    """If discover returns nothing, graph ends at the first router."""
    from agent.providers.discovery.base import CompanyDiscoveryProvider

    class EmptyDiscovery(CompanyDiscoveryProvider):
        def discover(self, keywords, location, limit):
            return []

    object.__setattr__(fake_bundle, "discovery", EmptyDiscovery())
    graph = build_graph(fake_bundle, repo, test_config, _LOG)

    initial: AgentState = {
        "config": test_config, "run_id": "test_early_end",
        "companies": [], "leads": [], "appended_row_count": 0,
        "draft_result": {}, "step_log": [], "errors": [],
    }
    final = graph.invoke(initial)

    # Only discover_companies should appear in step_log
    step_names = [r.step for r in final.get("step_log", [])]
    assert "discover_companies" in step_names
    assert "resolve_contacts" not in step_names
    assert final.get("appended_row_count", 0) == 0
