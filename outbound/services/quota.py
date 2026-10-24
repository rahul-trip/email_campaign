"""What a workspace may do and has left, read fresh each time (Phase 6d).

Nothing is cached: a platform admin who raises a limit, grants credits or extends access changes
what the next step sees, with no restart. A workspace with no plan row (one that existed before
plans did) is unlimited and never expires.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entitlements import Plan, Quota
from outbound.domain.enums import UsageStep
from outbound.domain.platform_settings import PlatformSettings
from outbound.metering.quota import quota_in


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
        with self._uow(self._workspace_id) as uow:
            return quota_in(uow, self._now())

    def plan(self) -> Plan:
        return self.quota().plan

    def charge(self, step: UsageStep, company_id: str) -> bool:
        """Charge ``step`` on a lead, once (True if this call did), in its own transaction."""
        with self._uow(self._workspace_id) as uow:
            charged = uow.usage.charge(step, company_id)
            uow.commit()
        return charged
