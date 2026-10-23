"""Moves companies through the stages, one lead at a time.

For each lead the runner (1) reads it and runs the guards, (2) calls the stage with no
transaction open, and (3) writes the answer in one short transaction. A failing lead is marked
``failed`` with its stage and error and the run carries on. Status is the queue: killing the
process at any point loses nothing, and the rerun repeats no paid call because every vendor
answer is already in the ledger.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Company
from outbound.domain.enums import (
    CompanyStatus,
    EntityType,
    HoldReason,
    MessageState,
    RunKind,
    RunStatus,
)
from outbound.domain.errors import ConfigurationError
from outbound.domain.state_machines import STAGE_INPUT_STATUS, retry_status_for
from outbound.logging import bind, get_logger, unbind
from outbound.metering.metered import call_scope
from outbound.runner.guards import Guards, Refusal, RefusalKind
from outbound.stages.base import Reader, Stage, StageContext, StageResult

log = get_logger(__name__)

MAX_ERROR_LENGTH = 300


class Outcome(StrEnum):
    ADVANCED = "advanced"
    HELD = "held"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    DEFERRED = "deferred"  # left where it is; will be tried again later
    SKIPPED = "skipped"  # changed under us, or an operator edit won the race


@dataclass
class RunReport:
    run_id: str
    status: RunStatus = RunStatus.RUNNING
    counts: dict[str, Counter[str]] = field(default_factory=dict)
    cost_micro_usd: int = 0

    def count(self, stage: str, outcome: Outcome) -> int:
        return self.counts.get(stage, Counter())[outcome.value]

    def to_json(self) -> dict[str, Any]:
        return {stage: dict(counter) for stage, counter in self.counts.items()}


class Runner:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        stages: Sequence[Stage],
        guards: Guards,
        *,
        retry_delay: timedelta = timedelta(minutes=15),
        defer_delay: timedelta = timedelta(hours=1),
        max_attempts: int = 3,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._stages = tuple(stages)
        self._guards = guards
        self._retry_delay = retry_delay
        self._defer_delay = defer_delay
        self._max_attempts = max_attempts
        self._read = Reader(uow_factory, workspace_id)
        self._now = now
        self._run_id: str | None = None  # the run whose lead is being processed, for its events

    # ------------------------------------------------------------------ pipeline

    def run_pipeline(
        self, *, limit: int = 50, only: Collection[str] | None = None, run_id: str | None = None
    ) -> RunReport:
        """Run every stage in order over the work that is due; at most ``limit`` leads each.

        With ``run_id`` the run was queued earlier (by the API); otherwise one is created.
        """
        with self._uow(self._workspace_id) as uow:
            if run_id is None:
                params = {"limit": limit, "only": sorted(only or [])}
                run_id = uow.runs.start(RunKind.PIPELINE, params)
            else:
                uow.runs.mark_running(run_id)
            uow.commit()
        report = RunReport(run_id)
        status = RunStatus.SUCCEEDED
        started = time.monotonic()
        bind(run_id=run_id, workspace_id=self._workspace_id)  # on every log line until we leave
        log.info(
            "run_started",
            stages=[s.name for s in self._stages if not only or s.name in only],
            limit_per_stage=limit,
        )
        try:
            for stage in self._stages:
                if only and stage.name not in only:
                    continue
                report.counts[stage.name] = self._run_stage(stage, run_id, limit)
                if self._cancelled(run_id):
                    status = RunStatus.CANCELLED
                    break
        except BaseException:
            self._finish(run_id, RunStatus.FAILED, report)
            log.error(
                "run_finished", status=RunStatus.FAILED.value, **self._summary(report, started)
            )
            raise
        finally:
            unbind("run_id", "workspace_id")
        self._finish(run_id, status, report)
        report.status = status
        log.info(
            "run_finished",
            run_id=run_id,
            status=status.value,
            **self._summary(report, started),
        )
        return report

    @staticmethod
    def _summary(report: RunReport, started: float) -> dict[str, Any]:
        return {
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cost_micro_usd": report.cost_micro_usd,
            "outcomes": report.to_json(),
        }

    def _run_stage(self, stage: Stage, run_id: str, limit: int) -> Counter[str]:
        counts: Counter[str] = Counter()
        with self._uow(self._workspace_id) as uow:
            waiting = uow.companies.due(stage.input_status, limit, self._now())
        for company in waiting:
            if self._cancelled(run_id):
                break
            counts[self._process(stage, company.id, run_id).value] += 1
        return counts

    def _finish(self, run_id: str, status: RunStatus, report: RunReport) -> None:
        with self._uow(self._workspace_id) as uow:
            uow.runs.finish(run_id, status, report.to_json())
            report.cost_micro_usd = uow.runs.cost_of(run_id)
            uow.commit()

    def _cancelled(self, run_id: str) -> bool:
        """Whether the operator cancelled the run; otherwise record that it is still alive."""
        with self._uow(self._workspace_id) as uow:
            if uow.runs.status(run_id) is RunStatus.CANCELLED:
                return True
            uow.runs.heartbeat(run_id)
            uow.commit()
            return False

    # ------------------------------------------------------------------ one lead

    def _process(self, stage: Stage, company_id: str, run_id: str) -> Outcome:
        # Everything about one lead, including loading it, is inside the try: whatever is wrong
        # with this lead must not stop the run for the others.
        company: Company | None = None
        result: StageResult | None = None
        bind(company_id=company_id, stage=stage.name)
        self._run_id = run_id
        try:
            with self._uow(self._workspace_id) as uow:
                company = uow.companies.get(company_id)
                if company.status is not stage.input_status:
                    return Outcome.SKIPPED  # someone moved it since the list was made
                refusal = self._guards.check(uow, company, stage)
                campaign = uow.campaigns.get(company.campaign_id) if company.campaign_id else None
                workspace = uow.workspace()
            if refusal is not None:
                return self._apply_refusal(stage, company, refusal)
            if workspace is None:
                raise ConfigurationError(f"workspace {self._workspace_id} does not exist")

            context = StageContext(company, workspace, campaign, self._read, self._now())
            with call_scope(run_id=run_id, company_id=company.id):
                result = stage.handle(context)
            return self._apply(stage, company, result)
        except ConcurrencyConflict:
            self._undo(result)
            return Outcome.SKIPPED
        except Exception as error:
            self._undo(result)
            if isinstance(error, NotFound) and not self._exists(company_id):
                # The operator deleted the lead while this stage was working on it.
                log.info("lead_gone_during_run", stage=stage.name, company_id=company_id)
                return Outcome.SKIPPED
            if company is None:  # the lead could not even be loaded
                log.exception("lead_unreadable", stage=stage.name, company_id=company_id)
                return Outcome.SKIPPED
            return self._record_failure(stage, company, error)
        finally:
            self._run_id = None
            unbind("company_id", "stage")

    def _exists(self, company_id: str) -> bool:
        with self._uow(self._workspace_id) as uow:
            try:
                uow.companies.get(company_id)
            except NotFound:
                return False
        return True

    @staticmethod
    def _undo(result: StageResult | None) -> None:
        """Take back an outside effect (a saved draft) when its database write did not happen."""
        if result is not None and result.undo is not None:
            try:
                result.undo()
            except Exception:
                log.exception("undo_failed")

    def _apply(self, stage: Stage, company: Company, result: StageResult) -> Outcome:
        with self._uow(self._workspace_id) as uow:
            current = company
            if result.company_updates:
                current = uow.companies.update_fields(
                    company.id,
                    result.company_updates,
                    actor=SYSTEM,
                    expected_version=current.row_version,
                )
            if result.write is not None:
                result.write(uow)
            uow.companies.transition(
                company.id,
                result.to_status,
                expected_version=current.row_version,
                actor=SYSTEM,
                reason=result.reason,
                hold_reason=result.hold_reason,
                next_action_at=result.next_action_at,
                run_id=self._run_id,
            )
            uow.commit()
        log.info(
            "stage_done",
            stage=stage.name,
            company_id=company.id,
            to_status=result.to_status.value,
            reason=result.reason,
        )
        return Outcome.HELD if result.to_status is CompanyStatus.HELD else Outcome.ADVANCED

    # ------------------------------------------------------------------ not going ahead

    def _apply_refusal(self, stage: Stage, company: Company, refusal: Refusal) -> Outcome:
        try:
            with self._uow(self._workspace_id) as uow:
                if refusal.kind is RefusalKind.SUPPRESSED:
                    uow.companies.transition(
                        company.id,
                        CompanyStatus.SUPPRESSED,
                        expected_version=company.row_version,
                        reason=refusal.reason,
                        run_id=self._run_id,
                    )
                    outcome = Outcome.SUPPRESSED
                elif refusal.kind is RefusalKind.HOLD:
                    # An email already approved for a lead that is now on hold is withdrawn: once
                    # the hold is released the lead is checked again and gets a fresh email.
                    if company.status is CompanyStatus.APPROVED:
                        self._withdraw_open_messages(uow, company.id)
                    uow.companies.transition(
                        company.id,
                        CompanyStatus.HELD,
                        expected_version=company.row_version,
                        reason=refusal.reason,
                        hold_reason=refusal.hold_reason or HoldReason.NEEDS_OPERATOR,
                        run_id=self._run_id,
                    )
                    outcome = Outcome.HELD
                elif refusal.kind is RefusalKind.BUDGET and stage.name in STAGE_INPUT_STATUS:
                    self._fail(uow, stage, company, refusal.reason)
                    outcome = Outcome.FAILED
                else:
                    self._defer(uow, company, f"guard: {refusal.reason}")
                    outcome = Outcome.DEFERRED
                uow.commit()
        except ConcurrencyConflict:
            return Outcome.SKIPPED
        log.info(
            "guard_refused",
            stage=stage.name,
            company_id=company.id,
            kind=refusal.kind.value,
            reason=refusal.reason,
            outcome=outcome.value,
        )
        return outcome

    def _record_failure(self, stage: Stage, company: Company, error: Exception) -> Outcome:
        message = f"{type(error).__name__}: {error}"[:MAX_ERROR_LENGTH]
        log.exception("stage_failed", error=message)
        try:
            with self._uow(self._workspace_id) as uow:
                current = uow.companies.get(company.id)
                if current.status is not stage.input_status:
                    return Outcome.SKIPPED
                if stage.name in STAGE_INPUT_STATUS:
                    self._fail(uow, stage, current, message)
                    outcome = Outcome.FAILED
                else:
                    self._defer(uow, current, message)
                    outcome = Outcome.DEFERRED
                uow.commit()
        except (ConcurrencyConflict, NotFound):
            return Outcome.SKIPPED
        return outcome

    def _fail(self, uow: UnitOfWork, stage: Stage, company: Company, message: str) -> None:
        # Back off a little longer after each failure so a broken vendor is not hammered.
        wait = self._retry_delay * (company.attempts + 1)
        uow.companies.transition(
            company.id,
            CompanyStatus.FAILED,
            expected_version=company.row_version,
            failed_stage=stage.name,
            last_error=message,
            next_action_at=self._now() + wait,
            run_id=self._run_id,
        )

    @staticmethod
    def _withdraw_open_messages(uow: UnitOfWork, company_id: str) -> None:
        for message in uow.messages.for_company(company_id):
            if message.state in (MessageState.GENERATED, MessageState.APPROVED):
                uow.messages.transition(
                    message.id,
                    MessageState.CANCELLED,
                    expected_version=message.row_version,
                    actor=SYSTEM,
                )

    def _defer(self, uow: UnitOfWork, company: Company, message: str) -> None:
        """Leave the company where it is, and look again later.

        A deferral is recorded once per distinct reason: repeating "mailbox unreachable" every
        hour would bury the timeline.
        """
        later = self._now() + self._defer_delay
        uow.companies.update_fields(
            company.id,
            {"next_action_at": later},
            actor=SYSTEM,
            expected_version=company.row_version,
        )
        reason = message[:MAX_ERROR_LENGTH]
        previous = [
            e for e in uow.events.for_entity(EntityType.COMPANY, company.id) if e.type == "deferred"
        ]
        if not previous or previous[-1].data.get("reason") != reason:
            detail: dict[str, Any] = {"reason": reason}
            if self._run_id:
                detail["run_id"] = self._run_id
            uow.events.append(EntityType.COMPANY, company.id, "deferred", SYSTEM, detail)

    def has_due_work(self) -> bool:
        """Whether any stage has a lead waiting; a tick skips the pipeline run otherwise."""
        statuses = [stage.input_status for stage in self._stages]
        with self._uow(self._workspace_id) as uow:
            return uow.companies.any_due(statuses, self._now())

    # ------------------------------------------------------------------ retries

    def retry_failed(self, *, limit: int = 50) -> int:
        """Send failed companies back to the stage that failed, if they still have attempts left."""
        retried = 0
        with self._uow(self._workspace_id) as uow:
            for company in uow.companies.due(CompanyStatus.FAILED, limit, self._now()):
                if company.attempts >= self._max_attempts or company.failed_stage is None:
                    continue
                uow.companies.transition(
                    company.id,
                    retry_status_for(company.failed_stage),
                    expected_version=company.row_version,
                    reason=f"retry after {company.failed_stage} failed",
                    next_action_at=None,
                )
                retried += 1
            uow.commit()
        return retried
