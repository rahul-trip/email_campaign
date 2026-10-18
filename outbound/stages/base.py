"""The contract between the runner and a stage.

A stage looks at one company and says what should happen to it; it does not write. The runner
applies the answer in one short transaction. Splitting "decide" from "write" is what keeps a
database transaction from staying open across a network call: ``handle`` is free to call
vendors, and the writes it wants are returned as data (``StageResult``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from outbound.db.repositories.companies import UNSET, Unset
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.entities import Campaign, Company, Workspace
from outbound.domain.enums import CompanyStatus, HoldReason


class StageFailure(Exception):
    """A lead cannot go on, for a reason the operator should read (shown as its last error)."""


class Reader:
    """Runs a read in its own short transaction, for stages that need more than the snapshot."""

    def __init__(self, factory: UnitOfWorkFactory, workspace_id: str) -> None:
        self._factory = factory
        self._workspace_id = workspace_id

    def __call__[T](self, query: Callable[[UnitOfWork], T]) -> T:
        with self._factory(self._workspace_id) as uow:
            return query(uow)


@dataclass(frozen=True)
class StageContext:
    company: Company
    workspace: Workspace
    campaign: Campaign | None
    read: Reader
    now: datetime


@dataclass(frozen=True)
class StageResult:
    """What the runner should write for this company.

    ``company_updates`` are engine-written fields (an operator's protected values are kept and
    the attempt is logged instead). ``write`` adds child rows, such as contacts or a message, in
    the same transaction as the status change, so a lead is never half-advanced.
    """

    to_status: CompanyStatus
    reason: str | None = None
    hold_reason: HoldReason | None = None
    company_updates: Mapping[str, Any] = field(default_factory=dict)
    next_action_at: datetime | Unset | None = UNSET
    write: Callable[[UnitOfWork], None] | None = None
    # Takes back an outside effect (such as a saved mailbox draft) if the database write above
    # does not happen, so the two cannot disagree.
    undo: Callable[[], None] | None = None


class Stage(Protocol):
    name: str  # also the ``failed_stage`` value, so it must be a key of STAGE_INPUT_STATUS to fail
    input_status: CompanyStatus
    guard_policy: bool  # re-check the country policy before running (every stage after the gate)
    spends: bool  # makes paid calls, so the per-prospect budget applies; free stages ignore it

    def handle(self, ctx: StageContext) -> StageResult: ...
