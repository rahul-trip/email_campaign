"""Runs the operator starts: queued by the API, executed by the worker, watched by polling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from outbound.db.repositories.audit import RunView
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

    def to_params(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "only": list(self.only),
            "mode": self.mode.value,
            "discover": self.discover,
            "campaign": self.campaign,
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

    def cancel(self, run_id: str) -> RunView:
        with self._uow(self._workspace_id) as uow:
            uow.runs.cancel(run_id)
            uow.commit()
            return uow.runs.get(run_id)
