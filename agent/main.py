#!/usr/bin/env python3
"""agent/main.py — CLI entry point for the LangGraph lead-generation agent.

Usage:
    python -m agent.main [--config PATH] [--dry-run] [--max-companies N]
                         [--max-leads N] [--no-drafts]

Exit codes:
    0  Success (all leads persisted, drafts synced)
    1  Config / abort error (invalid config, missing keys)
    2  Partial success (some steps failed; check errors in output)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path when called as `python -m agent.main`
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent.config.loader import load_config
from agent.config.models import ConfigError
from agent.graph.build import build_graph
from agent.graph.state import AgentState
from agent.observability.logging_setup import configure_logging
from agent.persistence.lead_repository import XlsxLeadRepository
from agent.providers.bundle import build_providers


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quantra Energy — LangGraph outbound lead-generation agent."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.yaml"),
        help="Path to config.yaml (default: agent/config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery → copy, but skip persisting rows and syncing drafts.",
    )
    parser.add_argument(
        "--max-companies",
        type=int,
        default=None,
        metavar="N",
        help="Override limits.max_companies for this run.",
    )
    parser.add_argument(
        "--max-leads",
        type=int,
        default=None,
        metavar="N",
        help="Override limits.max_leads for this run.",
    )
    parser.add_argument(
        "--no-drafts",
        action="store_true",
        help="Force run_drafts_after=False for this run.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # --- 1. Generate run_id and configure logging ----------------------------
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = configure_logging(run_id)

    # --- 2. Load config -------------------------------------------------------
    try:
        config = load_config(args.config)
    except (ConfigError, FileNotFoundError) as exc:
        logging.getLogger("agent").error("Config error: %s", exc)
        return 1

    # Apply CLI overrides
    if args.max_companies is not None:
        config = replace(config, max_companies=args.max_companies)
    if args.max_leads is not None:
        config = replace(config, max_leads=args.max_leads)
    if args.no_drafts:
        config = replace(config, run_drafts_after=False)
    if args.dry_run:
        config = replace(config, run_drafts_after=False)

    log.info("Agent starting — run_id=%s config=%s", run_id, args.config)
    log.info("Keywords: %s | Location: %s | max_companies=%d | max_leads=%d",
             config.keywords, config.location, config.max_companies, config.max_leads)

    # --- 3. Build providers and repository ------------------------------------
    try:
        bundle = build_providers(config)
        repo = XlsxLeadRepository(config.xlsx_path)
    except Exception as exc:
        log.error("Initialization error: %s", exc)
        return 1

    # --- 4. Build and run the graph ------------------------------------------
    graph = build_graph(bundle, repo, config, log)

    initial_state: AgentState = {
        "config": config,
        "run_id": run_id,
        "companies": [],
        "leads": [],
        "appended_row_count": 0,
        "draft_result": {},
        "step_log": [],
        "errors": [],
    }

    try:
        final_state = graph.invoke(initial_state)
    except Exception as exc:
        log.exception("Graph invocation failed: %s", exc)
        return 1

    # --- 5. Dry-run: print what would be written, then exit ------------------
    if args.dry_run:
        leads = final_state.get("leads", [])
        log.info("DRY RUN — %d lead(s) would be appended:", len(leads))
        for lead in leads:
            log.info("  • %s (%s) <%s>",
                     lead.contact.full_name, lead.company.name, lead.email.address)
        summary = {
            "dry_run": True,
            "leads_would_append": len(leads),
            "leads": [lead.to_row() for lead in leads],
            "errors": final_state.get("errors", []),
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    # --- 6. Build summary and print ------------------------------------------
    errors = final_state.get("errors", [])
    summary = {
        "run_id": run_id,
        "companies_found": len(final_state.get("companies", [])),
        "leads_persisted": final_state.get("appended_row_count", 0),
        "draft_result": final_state.get("draft_result", {}),
        "step_log": [
            {"step": r.step, "status": r.status, "detail": r.detail,
             "duration_ms": round(r.duration_ms)}
            for r in final_state.get("step_log", [])
        ],
        "errors": errors,
    }

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    log.info("Run complete: companies=%d persisted=%d errors=%d",
             summary["companies_found"], summary["leads_persisted"], len(errors))

    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
