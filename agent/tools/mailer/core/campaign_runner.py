"""The single entry point this whole package exists to expose as a tool.

`sync_campaign_to_drafts` takes plain arguments and returns a plain,
JSON-serializable result. It has no dependency on any agent framework, so it
can be wrapped as-is by a LangGraph tool node, a LangChain Tool, an OpenAI/
Anthropic function-calling tool, a cron job, or called straight from a CLI —
whatever the eventual agent turns out to be built on.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field, replace

from agent.tools.mailer.config.settings import Settings
from agent.tools.mailer.drafts import get_provider
from agent.tools.mailer.ingestion.xlsx_reader import XlsxSchemaError, read_campaign_rows

logger = logging.getLogger(__name__)


@dataclass
class RowResult:
    row_number: int
    to_addr: str
    subject: str
    status: str  # "drafted" | "failed" | "dry_run"
    detail: str = ""


@dataclass
class CampaignSyncResult:
    total_rows: int
    drafted: int
    failed: int
    dry_run: bool
    errors: list[str] = field(default_factory=list)
    results: list[RowResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def sync_campaign_to_drafts(
    *,
    xlsx_path: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    start_row: int | None = None,
    settings: Settings | None = None,
) -> CampaignSyncResult:
    """Read the campaign matrix and push each row into the mailbox's Drafts folder.

    Args:
        xlsx_path: Override the workbook path from config/settings for this call.
        dry_run: If True, don't connect to any mailbox or write anything — just
            report what would be drafted (subject/recipient per row).
        limit: Optional cap on number of rows processed, useful for a smoke test.
        start_row: When set, skip spreadsheet rows whose row number is less than
            this value (1-indexed, header is row 1). Used by the agent after
            appending new rows so only the freshly-appended rows are drafted.
            Default None = read all rows (unchanged behavior for existing callers).
        settings: Inject a pre-built Settings (e.g. from tests); defaults to
            loading from the environment/.env file.

    Returns:
        CampaignSyncResult — plain dataclass, safe to json.dumps(result.as_dict()).
    """
    settings = settings or Settings.from_env()
    if xlsx_path:
        settings = replace(settings, xlsx_path=xlsx_path)

    problems = settings.validate(require_credentials=not dry_run)
    if problems:
        return CampaignSyncResult(total_rows=0, drafted=0, failed=0, dry_run=dry_run, errors=problems)

    try:
        rows = read_campaign_rows(settings.xlsx_path, start_row=start_row)
    except XlsxSchemaError as exc:
        return CampaignSyncResult(total_rows=0, drafted=0, failed=0, dry_run=dry_run, errors=[str(exc)])

    if limit is not None:
        rows = rows[:limit]

    result = CampaignSyncResult(total_rows=len(rows), drafted=0, failed=0, dry_run=dry_run)

    if dry_run:
        for row in rows:
            result.results.append(
                RowResult(
                    row_number=row.row_number,
                    to_addr=row.to_addr,
                    subject=row.subject,
                    status="dry_run",
                    detail=f"body length={len(row.body)} chars",
                )
            )
        return result

    with get_provider(settings) as provider:
        for i, row in enumerate(rows):
            try:
                detail = provider.save_draft(to_addr=row.to_addr, subject=row.subject, body=row.body)
                result.results.append(
                    RowResult(row.row_number, row.to_addr, row.subject, "drafted", detail)
                )
                result.drafted += 1
                logger.info("Row %s -> drafted for %s", row.row_number, row.to_addr)
            except Exception as exc:
                result.results.append(
                    RowResult(row.row_number, row.to_addr, row.subject, "failed", str(exc))
                )
                result.failed += 1
                logger.error("Row %s -> failed for %s: %s", row.row_number, row.to_addr, exc)

            if settings.delay_seconds and i < len(rows) - 1:
                time.sleep(settings.delay_seconds)

    return result
