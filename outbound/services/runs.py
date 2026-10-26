"""Runs the operator starts: queued by the API, executed by the worker, watched by polling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from outbound.db.errors import NotFound
from outbound.db.repositories.audit import RunCallSummary, RunView
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import RunKind, RunStatus
from outbound.services import defaults


class RunMode(StrEnum):
    MANUAL = "manual"  # only the targets the operator added
    DISCOVERY = "discovery"  # also look for new companies first
    MIXED = "mixed"  # operator targets and discovered ones together


@dataclass(frozen=True)
class RunRequest:
    limit: int = 50
    only: tuple[str, ...] = ()
    mode: RunMode = RunMode.MANUAL
    discover: int = 10
    campaign: str = defaults.DEFAULT_CAMPAIGN_NAME
    # Find emails with the vendors, not the shared directory, for the leads this run works on.
    skip_directory: bool = False

    def to_params(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "only": list(self.only),
            "mode": self.mode.value,
            "discover": self.discover,
            "campaign": self.campaign,
            "skip_directory": self.skip_directory,
        }

    @classmethod
    def from_params(cls, params: dict[str, Any] | None) -> RunRequest:
        data = params or {}
        return cls(
            limit=int(data.get("limit", 50)),
            only=tuple(data.get("only", ())),
            mode=RunMode(data.get("mode", RunMode.MANUAL.value)),
            discover=int(data.get("discover", 10)),
            campaign=str(data.get("campaign", defaults.DEFAULT_CAMPAIGN_NAME)),
        )


@dataclass(frozen=True)
class RunLead:
    """What one run did to one lead: each status it moved the lead through, in order."""

    company_id: str
    domain: str
    name: str | None
    status: str  # where the lead is now
    steps: tuple[RunStep, ...]

    @property
    def outcome(self) -> str:
        """``failed`` if the run failed it, ``held`` if it ended held, else ``moved``."""
        last = self.steps[-1]
        if last.to_status == "failed":
            return "failed"
        if last.to_status == "held":
            return "held"
        if last.kind == "deferred":
            return "deferred"
        return "moved"


@dataclass(frozen=True)
class RunStep:
    at: datetime
    kind: str  # status_changed or deferred
    from_status: str | None
    to_status: str | None
    detail: str | None  # the reason, hold reason or error


@dataclass(frozen=True)
class DiscoverySearch:
    query: str
    new_leads: int
    already_leads: int


class RunService:
    def __init__(self, uow_factory: UnitOfWorkFactory, workspace_id: str) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id

    def queue(self, request: RunRequest) -> RunView:
        with self._uow(self._workspace_id) as uow:
            run_id = uow.runs.queue(RunKind.PIPELINE, request.to_params())
            uow.commit()
            return uow.runs.get(run_id)

    def get(self, run_id: str) -> RunView:
        with self._uow(self._workspace_id) as uow:
            run = uow.runs.get(run_id)
            if run.status is RunStatus.RUNNING:  # spend so far, before the run closes
                return RunView(
                    run.id,
                    run.kind,
                    run.status,
                    run.params,
                    run.counts,
                    uow.runs.cost_of(run_id),
                    run.started_at,
                    run.finished_at,
                    run.created_at,
                )
            return run

    def recent(self, limit: int = 20) -> list[RunView]:
        with self._uow(self._workspace_id) as uow:
            return uow.runs.recent(limit)

    def leads(self, run_id: str) -> list[RunLead]:
        """Every lead this run moved, held, failed or deferred, in the order it first touched
        them. A lead it looked at and left alone is not listed. Leads deleted since are left out.
        """
        with self._uow(self._workspace_id) as uow:
            uow.runs.get(run_id)  # NotFound for an unknown run or another workspace's
            events = uow.events.for_run(run_id, ("status_changed", "deferred"))
            steps: dict[str, list[RunStep]] = {}
            for event in events:
                data = event.data
                detail = data.get("error") or data.get("hold_reason") or data.get("reason")
                steps.setdefault(event.entity_id, []).append(
                    RunStep(
                        event.created_at,
                        event.type,
                        data.get("from"),
                        data.get("to"),
                        str(detail) if detail else None,
                    )
                )
            found: list[RunLead] = []
            for company_id, done in steps.items():
                try:
                    company = uow.companies.get(company_id)
                except NotFound:  # deleted since the run
                    continue
                found.append(
                    RunLead(
                        company_id,
                        company.domain,
                        company.name,
                        company.status.value,
                        tuple(done),
                    )
                )
            return found

    def calls(self, run_id: str) -> list[RunCallSummary]:
        """What the run spent, by vendor and operation."""
        with self._uow(self._workspace_id) as uow:
            uow.runs.get(run_id)  # NotFound for an unknown run or another workspace's
            return uow.calls.summary_for_run(run_id)

    def searches(self, run_id: str) -> list[DiscoverySearch]:
        """The web searches a run made to find new companies, with what each one found."""
        with self._uow(self._workspace_id) as uow:
            uow.runs.get(run_id)  # NotFound for an unknown run or another workspace's
            return [
                DiscoverySearch(
                    str(e.data.get("query", "")),
                    int(e.data.get("new", 0)),
                    int(e.data.get("already_leads", 0)),
                )
                for e in uow.events.for_run(run_id, ("discovery_query",))
            ]

    def cancel(self, run_id: str) -> RunView:
        with self._uow(self._workspace_id) as uow:
            uow.runs.cancel(run_id)
            uow.commit()
            return uow.runs.get(run_id)
