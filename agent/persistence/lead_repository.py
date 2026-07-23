"""agent/persistence/lead_repository.py — Repository for reading/writing leads to xlsx.

Repository pattern: this is the ONLY module that opens the workbook for
writing. The rest of the agent never touches openpyxl directly.

Mirror of tools/mailer/ingestion/xlsx_reader.py's header-mapping approach —
maps column names to indices rather than assuming fixed positions, so
column ordering in the workbook is irrelevant.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import openpyxl

from agent.domain.models import COLUMN_ORDER, Lead

logger = logging.getLogger("agent")


class XlsxSchemaError(ValueError):
    """Raised when the workbook is missing one of the required columns."""


class XlsxLeadRepository:
    """Read existing data and append new leads to the campaign matrix.

    Usage:
        repo = XlsxLeadRepository(config.xlsx_path)
        existing = repo.existing_domains()   # before discovery
        repo.append_leads(leads)             # after copy generation
    """

    def __init__(self, xlsx_path: str) -> None:
        self._path = Path(xlsx_path)
        if not self._path.exists():
            raise FileNotFoundError(
                f"Campaign matrix not found: {self._path}. "
                "Check output.xlsx_path in config.yaml."
            )
        self._header_index_cache: dict[str, int] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def existing_domains(self) -> set[str]:
        """Return the set of root domains already in the workbook.

        Reads the "Organization URL" column and extracts the URL line
        (second line of the cell, formatted as "Company Name\\nhttps://…").
        Used by discover_companies to filter already-known companies.
        """
        wb = openpyxl.load_workbook(str(self._path), read_only=True, data_only=True)
        ws = wb.active
        header_idx = self._get_header_index(ws)
        org_url_col = header_idx.get("Organization URL")
        if org_url_col is None:
            return set()

        domains: set[str] = set()
        for row in ws.iter_rows(min_row=2, values_only=True):
            cell_value = row[org_url_col] if len(row) > org_url_col else None
            if not cell_value:
                continue
            # Cell format: "Company Name\nhttps://..."
            lines = str(cell_value).splitlines()
            for line in lines:
                line = line.strip()
                if line.startswith("http"):
                    domain = _extract_domain(line)
                    if domain:
                        domains.add(domain)
        wb.close()
        logger.debug("existing_domains: found %d domains in workbook", len(domains))
        return domains

    def row_count(self) -> int:
        """Return the last populated data row number (1-indexed, header is row 1).

        Used to calculate start_row for the drafts tool so only newly-appended
        rows are drafted.
        """
        wb = openpyxl.load_workbook(str(self._path), read_only=True, data_only=True)
        ws = wb.active
        count = ws.max_row
        wb.close()
        return count  # includes the header row

    def append_leads(self, leads: list[Lead]) -> int:
        """Append each lead as a new row in the correct column positions.

        Preserves all existing rows and column order. Does not reformat
        or touch any existing cell.

        Args:
            leads: List of fully-populated Lead objects.

        Returns:
            Number of rows actually appended.
        """
        if not leads:
            return 0

        # Open without read_only so we can write
        wb = openpyxl.load_workbook(str(self._path), data_only=True)
        ws = wb.active

        header_idx = self._get_header_index(ws)

        appended = 0
        for lead in leads:
            row_data = lead.to_row()  # dict[str, str] with COLUMN_ORDER keys
            # Find the next empty row
            new_row = ws.max_row + 1
            for col_name, value in row_data.items():
                col_idx = header_idx.get(col_name)
                if col_idx is None:
                    logger.warning("Column %r not found in workbook — skipping", col_name)
                    continue
                # openpyxl columns are 1-indexed; header_idx is 0-indexed
                ws.cell(row=new_row, column=col_idx + 1, value=value)
            appended += 1
            logger.debug("Appended row %d: %s", new_row, lead.company.name)

        wb.save(str(self._path))
        wb.close()
        logger.info("append_leads: appended %d rows to %s", appended, self._path.name)
        return appended

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_header_index(self, ws) -> dict[str, int]:
        """Return {column_name: 0-based column index} for required columns.

        Raises XlsxSchemaError if any of COLUMN_ORDER columns are missing.
        """
        if self._header_index_cache is not None:
            return self._header_index_cache

        header_row = next(ws.iter_rows(max_row=1, values_only=True), [])
        header = [str(c).strip() if c is not None else "" for c in header_row]

        index: dict[str, int] = {}
        missing: list[str] = []
        for col_name in COLUMN_ORDER:
            try:
                index[col_name] = header.index(col_name)
            except ValueError:
                missing.append(col_name)

        if missing:
            raise XlsxSchemaError(
                f"Campaign matrix is missing required column(s): {missing}. "
                f"Found columns: {[h for h in header if h]}"
            )

        self._header_index_cache = index
        return index


def _extract_domain(url: str) -> str:
    """Extract root domain (no www.) from a URL string."""
    try:
        host = urlparse(url).hostname or ""
        return host.lower().removeprefix("www.")
    except Exception:
        return ""
