"""Runs and the provider-call ledger (response cache, spend, and audit in one table)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from outbound.db.models import ProviderCallRow, RunRow
from outbound.db.repositories.base import ScopedRepository
from outbound.db.types import utcnow
from outbound.domain.enums import CallOutcome, RunKind, RunStatus
from outbound.domain.state_machines import RUN

_REUSABLE = (CallOutcome.HIT, CallOutcome.MISS)  # a successful answer, including "nothing found"


@dataclass(frozen=True)
class RunView:
    id: str
    kind: RunKind
    status: RunStatus
    params: dict[str, Any] | None
    counts: dict[str, Any] | None
    cost_micro_usd: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RunRepository(ScopedRepository):
    def queue(self, kind: RunKind, params: dict[str, Any] | None = None) -> str:
        """Record a run for the worker to pick up; nothing is executed here."""
        row = RunRow(
            workspace_id=self._workspace_id, kind=kind, params=params, status=RunStatus.QUEUED
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def claim_next(self) -> RunView | None:
        """Take the oldest queued run and mark it running. Safe with several workers."""
        stmt = (
            select(RunRow)
            .where(RunRow.workspace_id == self._workspace_id, RunRow.status == RunStatus.QUEUED)
            .order_by(RunRow.created_at, RunRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = self._session.scalars(stmt).first()
        if row is None:
            return None
        row.status = RunStatus.RUNNING
        row.started_at = utcnow()
        self._session.flush()
        return self._view(row)

    def mark_running(self, run_id: str) -> None:
        row = self._row(RunRow, run_id)
        if RUN.allows(row.status, RunStatus.RUNNING):
            row.status = RunStatus.RUNNING
            row.started_at = utcnow()
            self._session.flush()

    def cancel(self, run_id: str) -> RunStatus:
        """Stop a queued run now, or ask a running one to stop between leads."""
        row = self._row(RunRow, run_id)
        if RUN.allows(row.status, RunStatus.CANCELLED):
            if row.status is RunStatus.QUEUED:
                row.finished_at = utcnow()
            row.status = RunStatus.CANCELLED
            self._session.flush()
        return row.status

    def get(self, run_id: str) -> RunView:
        return self._view(self._row(RunRow, run_id))

    def recent(self, limit: int = 20) -> list[RunView]:
        stmt = (
            select(RunRow)
            .where(RunRow.workspace_id == self._workspace_id)
            .order_by(RunRow.created_at.desc(), RunRow.id.desc())
            .limit(limit)
        )
        return [self._view(row) for row in self._session.scalars(stmt)]

    def live_cost(self, run_id: str) -> int:
        return self.cost_of(run_id)

    @staticmethod
    def _view(row: RunRow) -> RunView:
        return RunView(
            row.id,
            row.kind,
            row.status,
            row.params,
            row.counts,
            row.cost_micro_usd,
            row.started_at,
            row.finished_at,
            row.created_at,
        )

    def start(self, kind: RunKind, params: dict[str, Any] | None = None) -> str:
        row = RunRow(
            workspace_id=self._workspace_id,
            kind=kind,
            params=params,
            status=RunStatus.RUNNING,
            started_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def finish(self, run_id: str, status: RunStatus, counts: dict[str, Any] | None = None) -> None:
        row = self._row(RunRow, run_id)
        # A run that is already over (including one the operator cancelled) keeps its status:
        # "succeeded" never turns into "failed" because a later error was reported.
        if RUN.allows(row.status, status):
            row.status = status
        row.counts = counts
        row.finished_at = utcnow()
        row.cost_micro_usd = self.cost_of(run_id)
        self._session.flush()

    def status(self, run_id: str) -> RunStatus:
        return self._row(RunRow, run_id).status

    def cost_of(self, run_id: str) -> int:
        stmt = select(func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0)).where(
            ProviderCallRow.workspace_id == self._workspace_id, ProviderCallRow.run_id == run_id
        )
        return int(self._session.scalar(stmt) or 0)


class ProviderCallRepository(ScopedRepository):
    def record(
        self,
        *,
        provider: str,
        operation: str,
        request_hash: str,
        outcome: CallOutcome,
        cost_micro_usd: int = 0,
        response: dict[str, Any] | None = None,
        latency_ms: int | None = None,
        run_id: str | None = None,
        company_id: str | None = None,
        contact_id: str | None = None,
    ) -> str:
        row = ProviderCallRow(
            workspace_id=self._workspace_id,
            provider=provider,
            operation=operation,
            request_hash=request_hash,
            outcome=outcome,
            cost_micro_usd=cost_micro_usd,
            response=response,
            latency_ms=latency_ms,
            run_id=run_id,
            company_id=company_id,
            contact_id=contact_id,
        )
        self._session.add(row)
        self._session.flush()
        return row.id

    def cached_response(
        self, provider: str, operation: str, request_hash: str, since: datetime
    ) -> dict[str, Any] | None:
        """The newest successful answer to this exact request that is not older than ``since``.

        A miss ("nothing found") is reusable too: asking again would pay for the same nothing.
        """
        stmt = (
            select(ProviderCallRow.response)
            .where(
                ProviderCallRow.workspace_id == self._workspace_id,
                ProviderCallRow.provider == provider,
                ProviderCallRow.operation == operation,
                ProviderCallRow.request_hash == request_hash,
                ProviderCallRow.outcome.in_(_REUSABLE),
                ProviderCallRow.created_at >= since,
            )
            .order_by(ProviderCallRow.created_at.desc())
            .limit(1)
        )
        found = self._session.execute(stmt).first()
        return None if found is None else (found[0] or {})

    def for_company(self, company_id: str) -> list[ProviderCallRow]:
        """Every provider call about this lead, oldest first (the waterfall inspector)."""
        stmt = (
            select(ProviderCallRow)
            .where(
                ProviderCallRow.workspace_id == self._workspace_id,
                ProviderCallRow.company_id == company_id,
            )
            .order_by(ProviderCallRow.created_at, ProviderCallRow.id)
        )
        return list(self._session.scalars(stmt))

    def spend_since(self, provider: str, since: datetime) -> int:
        stmt = select(func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0)).where(
            ProviderCallRow.workspace_id == self._workspace_id,
            ProviderCallRow.provider == provider,
            ProviderCallRow.created_at >= since,
        )
        return int(self._session.scalar(stmt) or 0)

    def spend_on_company(self, company_id: str) -> int:
        stmt = select(func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0)).where(
            ProviderCallRow.workspace_id == self._workspace_id,
            ProviderCallRow.company_id == company_id,
        )
        return int(self._session.scalar(stmt) or 0)
