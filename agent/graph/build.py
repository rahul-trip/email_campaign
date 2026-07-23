"""agent/graph/build.py — Assembles the LangGraph StateGraph.

All nodes are injected with their dependencies via the make_* closures in
nodes.py. The graph topology exactly matches the AGENTIC_SYSTEM_PLAN.md spec:

    START
      └─► discover_companies
              ├─(end)──► END
              └─(continue)──► resolve_contacts
                                └─► find_emails
                                      └─► verify_emails
                                              ├─(end)──► END
                                              └─(continue)──► generate_copy
                                                                └─► persist_rows
                                                                      └─► sync_drafts
                                                                            └─► END

Note: confirm the exact LangGraph import surface against the installed version.
The stable API used here is:
    from langgraph.graph import StateGraph, START, END
If your installed version differs, adapt imports but keep node/edge topology identical.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from agent.config.models import AgentConfig
from agent.graph.nodes import (
    make_copy,
    make_discover,
    make_find,
    make_persist,
    make_resolve,
    make_sync,
    make_verify,
    route_after_discovery,
    route_after_verify,
)
from agent.graph.state import AgentState
from agent.persistence.lead_repository import XlsxLeadRepository
from agent.providers.bundle import ProviderBundle


def build_graph(
    bundle: ProviderBundle,
    repo: XlsxLeadRepository,
    config: AgentConfig,
    log: logging.Logger,
):
    """Build and compile the LangGraph pipeline.

    Args:
        bundle: All five provider instances (Strategy / DI).
        repo:   The xlsx repository (Repository pattern / DI).
        config: Immutable run configuration.
        log:    The agent logger for this run.

    Returns:
        A compiled LangGraph that accepts an AgentState-shaped dict via .invoke().
    """
    g = StateGraph(AgentState)

    # Register nodes
    g.add_node("discover_companies", make_discover(bundle, repo, log))
    g.add_node("resolve_contacts",   make_resolve(bundle, log))
    g.add_node("find_emails",        make_find(bundle, log))
    g.add_node("verify_emails",      make_verify(bundle, config, log))
    g.add_node("generate_copy",      make_copy(bundle, config, log))
    g.add_node("persist_rows",       make_persist(repo, log))
    g.add_node("sync_drafts",        make_sync(config, log))

    # Edges
    g.add_edge(START, "discover_companies")

    g.add_conditional_edges(
        "discover_companies",
        route_after_discovery,
        {"continue": "resolve_contacts", "end": END},
    )

    g.add_edge("resolve_contacts", "find_emails")
    g.add_edge("find_emails",      "verify_emails")

    g.add_conditional_edges(
        "verify_emails",
        route_after_verify,
        {"continue": "generate_copy", "end": END},
    )

    g.add_edge("generate_copy", "persist_rows")
    g.add_edge("persist_rows",  "sync_drafts")
    g.add_edge("sync_drafts",   END)

    return g.compile()
