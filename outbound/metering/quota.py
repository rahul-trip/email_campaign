"""AI credits in the pipeline (Phase 6d): what a workspace has left.

Every vendor and model call uses AI credits (``metered.py`` stamps them on the ledger). Here the
period's use is set against the plan's monthly credits and the grants, before work is started,
reading what is stored at that moment, so an admin's change applies to the next step with no
restart.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from outbound.db.errors import NotFound
from outbound.db.uow import UnitOfWork
from outbound.domain.entitlements import (
    UNLIMITED,
    PlanAssignment,
    Quota,
    compute_quota,
    period_bounds,
)
from outbound.domain.enums import CompanyStatus, UsageStep
from outbound.domain.platform_settings import PlatformSettings

# A pipeline stage is counted (for reports) when it succeeds, which is when the lead reaches
# this status. Its calls use AI credits whether it succeeds or not.
STAGE_CHARGES: dict[str, tuple[UsageStep, CompanyStatus]] = {
    "research": (UsageStep.RESEARCH, CompanyStatus.RESEARCHED),
    "email": (UsageStep.EMAIL, CompanyStatus.EMAIL_READY),
    "copy": (UsageStep.COPY, CompanyStatus.COPY_READY),
    "deliver": (UsageStep.DELIVER, CompanyStatus.IN_SEQUENCE),
}


# Where a lead waits when AI credits run out before a stage that makes paid calls.
WAIT_STEP: dict[str, UsageStep] = {
    "research": UsageStep.RESEARCH,
    "contacts": UsageStep.EMAIL,
    "email": UsageStep.EMAIL,
    "copy": UsageStep.COPY,
}


def quota_in(uow: UnitOfWork, now: datetime) -> tuple[Quota, PlatformSettings]:
    """The workspace's quota and the platform settings it was computed with, read inside an
    open unit of work. A workspace with no plan row is unlimited and never expires."""
    workspace = uow.workspace()
    if workspace is None:
        raise NotFound(f"workspace {uow.workspace_id}")
    settings, _ = uow.platform_settings.get()
    assignment = uow.usage.assignment() or PlanAssignment(
        UNLIMITED.code, workspace.created_at or now, None
    )
    start, end = period_bounds(assignment.started_at, now)
    quota = compute_quota(
        assignment,
        settings.plan(assignment.plan_code),
        uow.usage.overrides(),
        uow.usage.grants(),
        uow.usage.credits_used(start, end),
        workspace.status,
        now,
    )
    if settings.kill_runs:
        quota = replace(quota, engine=False)  # the platform's kill switch
    return quota, settings


def credit_left(uow: UnitOfWork, now: datetime) -> tuple[bool, datetime]:
    """Whether any AI credits are left, and when the period (and so the allowance) renews."""
    quota, _ = quota_in(uow, now)
    return quota.has_credits(), quota.period_end
