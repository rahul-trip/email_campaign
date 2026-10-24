"""What a workspace may do and has left, read fresh each time (Phase 6d).

Nothing is cached: a platform admin who raises a limit, grants credits or extends access changes
what the next step sees, with no restart. A workspace with no plan row (one that existed before
plans did) is unlimited and never expires.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from outbound.db.errors import NotFound
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entitlements import (
    UNLIMITED,
    Plan,
    PlanAssignment,
    Quota,
    compute_quota,
    period_bounds,
)
from outbound.domain.enums import UsageStep
from outbound.domain.platform_settings import PlatformSettings


class QuotaService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._now = now

    def quota(self) -> Quota:
        return self.snapshot()[0]

    def snapshot(self) -> tuple[Quota, PlatformSettings]:
        """The quota and the platform settings it was computed with (the kill switches, the
        announcement), in one short read."""
        now = self._now()
        with self._uow(self._workspace_id) as uow:
            workspace = uow.workspace()
            if workspace is None:
                raise NotFound(f"workspace {self._workspace_id}")
            settings, _ = uow.platform_settings.get()
            stored = uow.usage.assignment()
            overrides, grants = uow.usage.overrides(), uow.usage.grants()
            assignment = stored or PlanAssignment(UNLIMITED.code, workspace.created_at or now, None)
            plan = settings.plan(assignment.plan_code)
            start, end = period_bounds(assignment.started_at, now)
            used = uow.usage.used(start, end)
        quota = compute_quota(assignment, plan, overrides, grants, used, workspace.status, now)
        if settings.kill_runs:
            quota = replace(quota, engine=False)  # the platform's kill switch
        return quota, settings

    def plan(self) -> Plan:
        return self.quota().plan

    def charge(self, step: UsageStep, company_id: str) -> bool:
        """Charge ``step`` on a lead (once; True if this call did). Not used by stages, which
        charge in their own transaction; for services that already hold no transaction."""
        with self._uow(self._workspace_id) as uow:
            charged = uow.usage.charge(step, company_id)
            uow.commit()
        return charged
