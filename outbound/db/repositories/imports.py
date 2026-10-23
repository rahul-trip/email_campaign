"""Import batches and rows: the operator's raw input, kept exactly as supplied."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from outbound.db.models import ImportBatchRow, ImportRowRow
from outbound.db.repositories.base import ScopedRepository
from outbound.domain.enums import ImportAnchor, ImportRowStatus, ImportSource


@dataclass(frozen=True)
class ImportRowView:
    id: str
    batch_id: str
    row_number: int | None
    raw: dict[str, Any]
    anchor: ImportAnchor
    status: ImportRowStatus
    resolved_domain: str | None
    resolution_confidence: float | None
    reason: str | None
    company_id: str | None


@dataclass(frozen=True)
class ImportOrigin:
    """An input row that produced or joined a company, with the delivery it arrived in."""

    row: ImportRowView
    source: ImportSource
    filename: str | None
    created_by: str
    received_at: datetime


class ImportRepository(ScopedRepository):
    def create_batch(
        self,
        source: ImportSource,
        created_by: str,
        *,
        campaign_id: str | None = None,
        filename: str | None = None,
    ) -> str:
        row = ImportBatchRow(
            workspace_id=self._workspace_id,
            source=source,
            created_by=created_by,
            campaign_id=campaign_id,
            filename=filename,
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def add_row(
        self,
        batch_id: str,
        raw: dict[str, Any],
        anchor: ImportAnchor,
        status: ImportRowStatus,
        *,
        row_number: int | None = None,
        resolved_domain: str | None = None,
        resolution_confidence: float | None = None,
        reason: str | None = None,
        company_id: str | None = None,
    ) -> str:
        row = ImportRowRow(
            workspace_id=self._workspace_id,
            batch_id=batch_id,
            row_number=row_number,
            raw=raw,
            anchor=anchor,
            status=status,
            resolved_domain=resolved_domain,
            resolution_confidence=resolution_confidence,
            reason=reason,
            company_id=company_id,
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def finish_batch(self, batch_id: str) -> dict[str, int]:
        """Store and return how many rows ended in each status."""
        stmt = select(ImportRowRow.status).where(
            ImportRowRow.workspace_id == self._workspace_id, ImportRowRow.batch_id == batch_id
        )
        counts: dict[str, int] = {"read": 0}
        for status in self._session.scalars(stmt):
            counts["read"] += 1
            counts[status.value] = counts.get(status.value, 0) + 1
        self._row(ImportBatchRow, batch_id).counts = counts
        self._session.flush()
        return counts

    def row_statuses(self, batch_id: str) -> list[ImportRowStatus]:
        stmt = (
            select(ImportRowRow.status)
            .where(
                ImportRowRow.workspace_id == self._workspace_id, ImportRowRow.batch_id == batch_id
            )
            .order_by(ImportRowRow.row_number, ImportRowRow.id)
        )
        return list(self._session.scalars(stmt))

    def batch_exists(self, source: ImportSource, filename: str) -> bool:
        stmt = select(ImportBatchRow.id).where(
            ImportBatchRow.workspace_id == self._workspace_id,
            ImportBatchRow.source == source,
            ImportBatchRow.filename == filename,
        )
        return self._session.scalars(stmt).first() is not None

    def batch_campaign(self, batch_id: str) -> str | None:
        return self._row(ImportBatchRow, batch_id).campaign_id

    def get_row(self, row_id: str) -> ImportRowView:
        return self._view(self._row(ImportRowRow, row_id))

    def origins_for_company(self, company_id: str) -> list[ImportOrigin]:
        """Every input row that led to the company, oldest first."""
        stmt = (
            select(ImportRowRow, ImportBatchRow)
            .join(
                ImportBatchRow,
                (ImportBatchRow.id == ImportRowRow.batch_id)
                & (ImportBatchRow.workspace_id == ImportRowRow.workspace_id),
            )
            .where(
                ImportRowRow.workspace_id == self._workspace_id,
                ImportRowRow.company_id == company_id,
            )
            .order_by(ImportBatchRow.created_at, ImportRowRow.row_number)
        )
        return [
            ImportOrigin(
                self._view(row), batch.source, batch.filename, batch.created_by, batch.created_at
            )
            for row, batch in self._session.execute(stmt)
        ]

    def rows_with_status(self, status: ImportRowStatus, limit: int = 200) -> list[ImportRowView]:
        stmt = (
            select(ImportRowRow)
            .where(ImportRowRow.workspace_id == self._workspace_id, ImportRowRow.status == status)
            .order_by(ImportRowRow.created_at, ImportRowRow.row_number)
            .limit(limit)
        )
        return [self._view(row) for row in self._session.scalars(stmt)]

    def settle_row(
        self,
        row_id: str,
        status: ImportRowStatus,
        *,
        resolved_domain: str | None,
        resolution_confidence: float | None,
        reason: str | None,
        company_id: str | None,
    ) -> None:
        """Record the outcome of re-examining a row (for example after the operator confirmed)."""
        row = self._row(ImportRowRow, row_id)
        row.status = status
        row.resolved_domain = resolved_domain
        row.resolution_confidence = resolution_confidence
        row.reason = reason
        row.company_id = company_id
        self._session.flush()

    @staticmethod
    def _view(row: ImportRowRow) -> ImportRowView:
        return ImportRowView(
            id=row.id,
            batch_id=row.batch_id,
            row_number=row.row_number,
            raw=dict(row.raw),
            anchor=row.anchor,
            status=row.status,
            resolved_domain=row.resolved_domain,
            resolution_confidence=row.resolution_confidence,
            reason=row.reason,
            company_id=row.company_id,
        )
