"""Moves companies through the stages, one lead at a time.

For each lead the runner (1) reads it and runs the guards, (2) calls the stage with no
transaction open, and (3) writes the answer in one short transaction. A failing lead is marked
``failed`` with its stage and error and the run carries on. Status is the queue: killing the
process at any point loses nothing, and the rerun repeats no paid call because every vendor
answer is already in the ledger.
"""

from __future__ import annotations

import contextvars
import itertools
import threading
import time
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
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
    FailureKind,
    HoldReason,
    MessageState,
    RunKind,
    RunStatus,
)
from outbound.domain.errors import ConfigurationError
from outbound.domain.outcomes import ERROR_TRIES, OUTCOME_TRIES
from outbound.domain.state_machines import STAGE_INPUT_STATUS, retry_status_for
from outbound.logging import bind, get_logger, unbind
from outbound.metering.metered import call_scope
from outbound.metering.quota import STAGE_CHARGES
from outbound.runner.guards import Guards, Refusal, RefusalKind
from outbound.stages.base import (
    Reader,
    Stage,
    StageContext,
    StageFailure,
    StageResult,
    VendorUnavailable,
)

log = get_logger(__name__)

MAX_ERROR_LENGTH = 300

# The run whose lead this task is processing, for the events it writes. Per task, not per runner,
# so several leads can be worked on at once (a ContextVar is private to each copied context).
_current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "runner_run", default=None
)


class Outcome(StrEnum):
    ADVANCED = "advanced"
    HELD = "held"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    DEFERRED = "deferred"  # left where it is; will be tried again later
    WAITING = "waiting"  # left where it is until a credit for the step exists (Phase 6d)
    SKIPPED = "skipped"  # changed under us, or an operator edit won the race


@dataclass
class RunReport:
    run_id: str
    status: RunStatus = RunStatus.RUNNING
    counts: dict[str, Counter[str]] = field(default_factory=dict)
    credits_milli: int = 0  # AI credits the run used, in thousandths

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
        vendor_wait: timedelta = timedelta(hours=2),
        outcome_delay: timedelta = timedelta(hours=24),
        max_attempts: int = ERROR_TRIES,
        max_outcome_attempts: int = OUTCOME_TRIES,
        lead_concurrency: int = 1,
        lead_flow: bool = False,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._stages = tuple(stages)
        self._guards = guards
        self._retry_delay = retry_delay
        self._vendor_wait = vendor_wait
        self._defer_delay = defer_delay
        self._outcome_delay = outcome_delay
        self._max_attempts = max_attempts
        self._max_outcome_attempts = max_outcome_attempts
        self._lead_concurrency = max(1, lead_concurrency)  # leads of one stage worked on at once
        self._lead_flow = lead_flow  # carry each lead through the stages, not stage by stage
        self._read = Reader(uow_factory, workspace_id)
        self._now = now

    # ------------------------------------------------------------------ pipeline

    def run_pipeline(
        self,
        *,
        limit: int = 50,
        only: Collection[str] | None = None,
        run_id: str | None = None,
        extra_counts: Mapping[str, Counter[str]] | None = None,
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
        report.counts.update(extra_counts or {})  # what happened before the stages (discovery)
        status = RunStatus.SUCCEEDED
        started = time.monotonic()
        bind(run_id=run_id, workspace_id=self._workspace_id)  # on every log line until we leave
        log.info(
            "run_started",
            stages=[s.name for s in self._stages if not only or s.name in only],
            limit_per_stage=limit,
        )
        try:
            active = [stage for stage in self._stages if not only or stage.name in only]
            rest = active
            if self._lead_flow and not only:
                # Each lead goes through as many stages as it can in one go; what is left (a stage
                # that works one lead at a time, such as delivery) runs as a pass of its own.
                flowing = list(itertools.takewhile(lambda s: getattr(s, "parallel", True), active))
                rest = active[len(flowing) :]
                report.counts.update({stage.name: Counter() for stage in flowing})
                self._run_flow(flowing, run_id, limit, report.counts)
                if self._cancelled(run_id):
                    status = RunStatus.CANCELLED
                    rest = []
            for stage in rest:
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
            "credits_milli": report.credits_milli,
            "outcomes": report.to_json(),
        }

    def _run_stage(self, stage: Stage, run_id: str, limit: int) -> Counter[str]:
        counts: Counter[str] = Counter()
        with self._uow(self._workspace_id) as uow:
            waiting = uow.companies.due(stage.input_status, limit, self._now())
        # A stage that shares one outside connection (delivery) says ``parallel = False``.
        workers = self._lead_concurrency if getattr(stage, "parallel", True) else 1
        if workers <= 1 or len(waiting) <= 1:
            for company in waiting:
                if self._cancelled(run_id):
                    break
                counts[self._process(stage, company.id, run_id).value] += 1
            return counts

        # Several leads at once: each is slow (a site, a search, a model), and they are
        # independent. Each task has its own copy of the logging and call context, so a lead's
        # calls and events carry its own ids; a cancelled run stops starting new leads.
        stop = threading.Event()

        def one(company_id: str) -> Outcome | None:
            if stop.is_set() or self._cancelled(run_id):
                stop.set()
                return None
            return self._process(stage, company_id, run_id)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lead") as pool:
            futures = [
                pool.submit(contextvars.copy_context().run, one, company.id) for company in waiting
            ]
            for future in futures:
                outcome = future.result()
                if outcome is not None:
                    counts[outcome.value] += 1
        return counts

    def _run_flow(
        self,
        stages: Sequence[Stage],
        run_id: str,
        limit: int,
        counts: dict[str, Counter[str]],
    ) -> None:
        """Take every due lead through the stages one after another, several leads at a time.

        A lead starts at the stage its status is waiting for and goes on while each step
        advances it; it stops where it is held, failed, deferred, refused or finished. Leads
        furthest along are taken first, so their drafts do not wait behind new leads' research.
        Each step is the same ``_process`` as in a stage-by-stage run, so each writes its own
        row and events; only the order in which leads and stages are visited differs.
        """
        with self._uow(self._workspace_id) as uow:
            starts = [
                (index, company.id)
                for index in reversed(range(len(stages)))
                for company in uow.companies.due(stages[index].input_status, limit, self._now())
            ]
        lock = threading.Lock()
        stop = threading.Event()

        def lead(start: int, company_id: str) -> None:
            index = start
            while index < len(stages):
                if stop.is_set() or self._cancelled(run_id):
                    stop.set()
                    return
                stage = stages[index]
                outcome = self._process(stage, company_id, run_id)
                if index > start and outcome is Outcome.SKIPPED:
                    return  # no stage waits for it here: nothing was tried, so nothing is counted
                with lock:
                    counts[stage.name][outcome.value] += 1
                if outcome is not Outcome.ADVANCED:
                    return
                index += 1

        with ThreadPoolExecutor(
            max_workers=self._lead_concurrency, thread_name_prefix="lead"
        ) as pool:
            futures = [
                pool.submit(contextvars.copy_context().run, lead, start, company_id)
                for start, company_id in starts
            ]
            for future in futures:
                future.result()

    def _finish(self, run_id: str, status: RunStatus, report: RunReport) -> None:
        with self._uow(self._workspace_id) as uow:
            uow.runs.finish(run_id, status, report.to_json())
            report.credits_milli = uow.runs.credits_of(run_id)
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
        run_token = _current_run.set(run_id)
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
            _current_run.reset(run_token)
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
                run_id=_current_run.get(),
            )
            # The step succeeded, so it is counted for reports, in the same transaction as its
            # result, once per lead. (Its calls already used their AI credits.)
            charge = STAGE_CHARGES.get(stage.name)
            if charge is not None and result.to_status is charge[1]:
                uow.usage.charge(charge[0], company.id)
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
                        run_id=_current_run.get(),
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
                        run_id=_current_run.get(),
                    )
                    outcome = Outcome.HELD
                elif refusal.kind is RefusalKind.ACCESS:
                    # The workspace may not run (paused, access ended, stopped). Nothing is
                    # written and no back-off is set, so the lead continues the moment it can.
                    outcome = Outcome.WAITING
                elif refusal.kind is RefusalKind.CREDITS and refusal.step is not None:
                    # Not a failure and not a hold: the lead keeps its status, loses nothing
                    # (an approved email stays approved) and is picked up when credits exist.
                    uow.companies.wait_for_credit(company.id, refusal.step)
                    outcome = Outcome.WAITING
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
        # A stage's own message is written for a person ("people were found, but none is a
        # decision-maker"); only an unexpected error needs its class name, for whoever debugs it.
        own = isinstance(error, StageFailure)
        message = (str(error) if own else f"{type(error).__name__}: {error}")[:MAX_ERROR_LENGTH]
        log.exception("stage_failed", error=message)
        try:
            with self._uow(self._workspace_id) as uow:
                current = uow.companies.get(company.id)
                if current.status is not stage.input_status:
                    return Outcome.SKIPPED
                if stage.name in STAGE_INPUT_STATUS:
                    self._fail(
                        uow,
                        stage,
                        current,
                        message,
                        vendor=isinstance(error, VendorUnavailable),
                        kind=error.kind if isinstance(error, StageFailure) else FailureKind.ERROR,
                    )
                    outcome = Outcome.FAILED
                else:
                    self._defer(uow, current, message)
                    outcome = Outcome.DEFERRED
                uow.commit()
        except (ConcurrencyConflict, NotFound):
            return Outcome.SKIPPED
        return outcome

    def _fail(
        self,
        uow: UnitOfWork,
        stage: Stage,
        company: Company,
        message: str,
        *,
        vendor: bool = False,
        kind: FailureKind = FailureKind.ERROR,
    ) -> None:
        # Back off a little longer after each failure so a broken vendor is not hammered. When no
        # vendor could answer, the lead is not at fault: it waits a fixed while and no attempt
        # is counted, so it is picked up again whenever a vendor is back.
        # "Nobody to write to" is an answer, not a breakage: ask again a day later, not in minutes.
        if vendor:
            wait = self._vendor_wait
        elif kind is not FailureKind.ERROR:
            wait = self._outcome_delay
        else:
            wait = self._retry_delay * (company.attempts + 1)
        uow.companies.transition(
            company.id,
            CompanyStatus.FAILED,
            expected_version=company.row_version,
            failed_stage=stage.name,
            last_error=message,
            failure_kind=kind,
            next_action_at=self._now() + wait,
            run_id=_current_run.get(),
            vendor_wait=vendor,
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
            if run_id := _current_run.get():
                detail["run_id"] = run_id
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
                limit = (
                    self._max_attempts
                    if company.failure_kind in (None, FailureKind.ERROR)
                    else self._max_outcome_attempts
                )
                if company.attempts >= limit or company.failed_stage is None:
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
