"""Letting work that waits for credits continue (Phase 6d).

Work waits in two places: a lead parked mid-pipeline (``companies.credit_wait_step``) and a
manual row that was a good lead but over the limit (a pending import row). Both wait in place,
nothing is lost, and both are released when a credit exists: by the tick as soon as credits
appear (a new period, a grant, a raised limit, extended access), or by a person pressing Resume.
Release is oldest first and never more than the credits available.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Company
from outbound.domain.entitlements import Quota
from outbound.domain.enums import UsageStep
from outbound.logging import get_logger
from outbound.metering.quota import quota_in
from outbound.services.intake import IntakeService

log = get_logger(__name__)


class NoCredits(Exception):
    """Resume was asked for but nothing can be released: no credit, or the workspace may not run."""

    def __init__(self, step: UsageStep | None, renews: datetime, reason: str) -> None:
        super().__init__(reason)
        self.step, self.renews, self.reason = step, renews, reason


@dataclass(frozen=True)
class Released:
    leads: int = 0
    rows: int = 0

    @property
    def total(self) -> int:
        return self.leads + self.rows


class ResumeService:
    name = "credit_resume"  # a tick job: the run report shows what it released

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        intake: IntakeService,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._intake = intake
        self._now = now

    # ------------------------------------------------------------------ what waits

    def waiting(self) -> tuple[Counter[str], int]:
        """Leads waiting per step, and manual rows waiting."""
        with self._uow(self._workspace_id) as uow:
            leads = uow.companies.waiting_for_credits()
        rows = self._intake.waiting_for_credits()
        return Counter(c.credit_wait_step.value for c in leads if c.credit_wait_step), len(rows)

    # ------------------------------------------------------------------ releasing

    def run(self) -> dict[str, int]:
        """The tick job: release whatever the credits now allow."""
        released = self.release_all(actor=SYSTEM, quietly=True)
        return {"leads": released.leads, "rows": released.rows}

    def release_all(self, *, actor: str, quietly: bool = False) -> Released:
        """Release waiting leads and rows up to the credits available. With ``quietly`` it just
        releases less (or nothing); otherwise it explains why nothing could be released."""
        now = self._now()
        rows_waiting = bool(self._intake.waiting_for_credits())
        with self._uow(self._workspace_id) as uow:
            quota, _ = quota_in(uow, now)
            waiting = uow.companies.waiting_for_credits()
            if not waiting and not rows_waiting:
                return Released()
            if not quota.engine:
                if quietly:
                    return Released()
                raise NoCredits(None, quota.period_end, _why_stopped(quota))
            leads = self._release_leads(uow, quota, waiting, actor)
            uow.commit()
        rows = self._intake.release_waiting(actor=actor)
        if (
            not quietly
            and leads == 0
            and rows == 0
            and (waiting or self._intake.waiting_for_credits())
        ):
            step = waiting[0].credit_wait_step if waiting else UsageStep.MANUAL
            raise NoCredits(step, quota.period_end, f"no {step.value if step else ''} credit yet")
        if leads or rows:
            log.info("credits_resumed", leads=leads, rows=rows)
        return Released(leads, rows)

    def resume_lead(self, company_id: str, *, actor: str) -> UsageStep:
        """Resume one waiting lead if its step now has a credit; otherwise say when it renews."""
        now = self._now()
        with self._uow(self._workspace_id) as uow:
            quota, _ = quota_in(uow, now)
            company = uow.companies.get(company_id)
            step = company.credit_wait_step
            if step is None:
                raise NoCredits(None, quota.period_end, "this lead is not waiting for credits")
            if not quota.engine:
                raise NoCredits(step, quota.period_end, _why_stopped(quota))
            if not (quota.has_credit(step) or uow.usage.charged(step, company_id)):
                raise NoCredits(step, quota.period_end, f"no {step.value} credit left")
            uow.companies.release_credit_wait(company_id, actor)
            uow.commit()
        return step

    @staticmethod
    def _release_leads(
        uow: UnitOfWork,
        quota: Quota,
        waiting: list[Company],
        actor: str,
    ) -> int:
        left: dict[UsageStep, int | None] = {s: quota.remaining(s) for s in UsageStep}
        released = 0
        for company in waiting:  # oldest first
            step = company.credit_wait_step
            if step is None:
                continue
            paid = uow.usage.charged(step, company.id)
            if not paid:
                remaining = left[step]
                if remaining is not None and remaining <= 0:
                    continue  # no credit for this one; another step's lead may still go
                if remaining is not None:
                    left[step] = remaining - 1
            uow.companies.release_credit_wait(company.id, actor)
            released += 1
        return released


def _why_stopped(quota: Quota) -> str:
    return (
        "access has ended" if quota.access.value == "read_only" else "the workspace is not running"
    )
