"""Runs and the provider-call ledger (response cache, spend, and audit in one table)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from outbound.db.errors import RunInProgress
from outbound.db.models import ProviderCallRow, RunRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.db.types import utcnow
from outbound.domain.entities import ProviderCall
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
        """Take the oldest queued run and mark it running. Safe with several workers.

        While a pipeline run is running in this workspace, queued pipeline runs wait: two at
        once would pay twice for the same vendor calls (``ux_runs_one_running_pipeline``).
        """
        stmt = (
            select(RunRow)
            .where(RunRow.workspace_id == self._workspace_id, RunRow.status == RunStatus.QUEUED)
            .order_by(RunRow.created_at, RunRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if self.pipeline_running():
            stmt = stmt.where(RunRow.kind != RunKind.PIPELINE)
        row = self._session.scalars(stmt).first()
        if row is None:
            return None
        row.status = RunStatus.RUNNING
        row.started_at = row.heartbeat_at = utcnow()
        self._flush_run()
        return self._view(row)

    def pipeline_running(self) -> bool:
        stmt = select(RunRow.id).where(
            RunRow.workspace_id == self._workspace_id,
            RunRow.status == RunStatus.RUNNING,
            RunRow.kind == RunKind.PIPELINE,
        )
        return self._session.scalars(stmt).first() is not None

    def mark_running(self, run_id: str) -> None:
        row = self._row(RunRow, run_id)
        if RUN.allows(row.status, RunStatus.RUNNING):
            row.status = RunStatus.RUNNING
            row.started_at = row.heartbeat_at = utcnow()
            self._flush_run()

    def heartbeat(self, run_id: str) -> None:
        """The runner is alive and working on this run."""
        self._row(RunRow, run_id).heartbeat_at = utcnow()
        self._session.flush()

    def fail_stale(self, cutoff: datetime) -> list[str]:
        """Fail running runs with no heartbeat since ``cutoff``: their worker stopped.

        Without this, a run whose worker died stays ``running`` for ever and blocks the queue.
        """
        stmt = select(RunRow).where(
            RunRow.workspace_id == self._workspace_id,
            RunRow.status == RunStatus.RUNNING,
            or_(
                RunRow.heartbeat_at < cutoff,
                RunRow.heartbeat_at.is_(None) & (RunRow.started_at < cutoff),
                RunRow.heartbeat_at.is_(None) & RunRow.started_at.is_(None),
            ),
        )
        failed = []
        for row in self._session.scalars(stmt):
            row.status = RunStatus.FAILED
            row.finished_at = utcnow()
            row.counts = {**(row.counts or {}), "error": "worker stopped (no heartbeat)"}
            failed.append(row.id)
        self._session.flush()
        return failed

    def _flush_run(self) -> None:
        try:
            self._session.flush()
        except IntegrityError as error:
            raise RunInProgress("another pipeline run is already running here") from error

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
            heartbeat_at=utcnow(),
        )
        if kind is RunKind.PIPELINE and self.pipeline_running():
            raise RunInProgress("another pipeline run is already running here")
        self._session.add(row)
        self._flush_run()
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


@dataclass(frozen=True)
class RunCallSummary:
    """What one run asked of one vendor operation, added up."""

    provider: str
    operation: str
    calls: int  # every row, including answers reused from the cache
    found: int  # paid calls that returned something
    nothing: int  # paid calls that found nothing
    reused: int  # answered from the cache, at no cost
    errors: int
    blocked: int  # refused by a spending limit
    cost_micro_usd: int
    avg_latency_ms: int | None


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

    def summary_for_run(self, run_id: str) -> list[RunCallSummary]:
        """The run's vendor calls grouped by vendor and operation, the costliest first."""
        stmt = (
            select(
                ProviderCallRow.provider,
                ProviderCallRow.operation,
                ProviderCallRow.outcome,
                func.count(),
                func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0),
                func.avg(ProviderCallRow.latency_ms),
            )
            .where(
                ProviderCallRow.workspace_id == self._workspace_id,
                ProviderCallRow.run_id == run_id,
            )
            .group_by(ProviderCallRow.provider, ProviderCallRow.operation, ProviderCallRow.outcome)
        )
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for provider, operation, outcome, count, cost, latency in self._session.execute(stmt):
            row = merged.setdefault(
                (provider, operation),
                {"found": 0, "nothing": 0, "reused": 0, "errors": 0, "blocked": 0,
                 "calls": 0, "cost": 0, "latency": []},
            )  # fmt: skip
            key = {
                CallOutcome.HIT: "found",
                CallOutcome.MISS: "nothing",
                CallOutcome.CACHE_HIT: "reused",
                CallOutcome.ERROR: "errors",
                CallOutcome.BLOCKED_BY_CAP: "blocked",
            }[outcome]
            row[key] += int(count)
            row["calls"] += int(count)
            row["cost"] += int(cost)
            if latency is not None:
                row["latency"].append(float(latency))
        out = [
            RunCallSummary(
                provider, operation, r["calls"], r["found"], r["nothing"], r["reused"],
                r["errors"], r["blocked"], r["cost"],
                round(sum(r["latency"]) / len(r["latency"])) if r["latency"] else None,
            )
            for (provider, operation), r in merged.items()
        ]  # fmt: skip
        return sorted(out, key=lambda c: (-c.cost_micro_usd, c.provider, c.operation))

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

    def for_company(self, company_id: str) -> list[ProviderCall]:
        """Every provider call about this lead, oldest first (the waterfall inspector)."""
        stmt = (
            select(ProviderCallRow)
            .where(
                ProviderCallRow.workspace_id == self._workspace_id,
                ProviderCallRow.company_id == company_id,
            )
            .order_by(ProviderCallRow.created_at, ProviderCallRow.id)
        )
        return [snapshot(row, ProviderCall) for row in self._session.scalars(stmt)]

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
