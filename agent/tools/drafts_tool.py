"""agent/tools/drafts_tool.py — Thin adapter over the mailer tool.

mailer/ lives at agent/tools/mailer/ — a self-contained Campaign-to-Drafts
tool the agent calls as its final pipeline step (Module F). It stays a
separate, framework-free package (own config, own tests) so it's still
usable standalone (see agent/tools/mailer/README.md); this file is just the
thin bridge that lets a LangGraph node invoke it as a tool.

The agent passes start_row = (pre-append row_count + 1) so only newly-appended
rows are drafted, not all historical rows.
"""

from __future__ import annotations

import logging

from agent.tools.mailer.core.campaign_runner import sync_campaign_to_drafts

logger = logging.getLogger("agent")


def run_drafts_sync(
    xlsx_path: str,
    start_row: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Invoke the mailer tool's Campaign-to-Drafts sync for newly-appended rows only.

    Args:
        xlsx_path:  Absolute path to the campaign xlsx workbook.
        start_row:  First spreadsheet row to draft (1-indexed). When set,
                    rows before this number are skipped (they were already
                    drafted in a prior run). None = all rows.
        dry_run:    If True, pass dry_run=True to the mailer (no IMAP writes).

    Returns:
        CampaignSyncResult.as_dict() — plain JSON-serializable dict.
    """
    logger.info("drafts_tool: invoking sync_campaign_to_drafts start_row=%s dry_run=%s",
                start_row, dry_run)
    try:
        result = sync_campaign_to_drafts(
            xlsx_path=xlsx_path,
            dry_run=dry_run,
            start_row=start_row,
        )
        return result.as_dict()
    except Exception as exc:
        logger.error("drafts_tool: sync_campaign_to_drafts failed: %s", exc)
        return {"error": str(exc), "drafted": 0, "failed": 0}
