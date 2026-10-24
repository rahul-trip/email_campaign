"""A workspace's plan and use, as the Plan & usage page shows it (Phase 6d)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entitlements import Grant, Quota
from outbound.domain.enums import UsageStep
from outbound.domain.errors import InvalidInput
from outbound.services.quota import QuotaService
from outbound.services.resume import ResumeService


@dataclass(frozen=True)
class UsageReport:
    quota: Quota
    grants: list[Grant]
    waiting_by_step: dict[str, int]
    waiting_rows: int
    announcement: str
    requested_at: datetime | None  # the latest "ask for more credits" still open


class UsageService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        identity: IdentityUnitOfWorkFactory,
        workspace_id: str,
        quota: QuotaService,
        resume: ResumeService,
    ) -> None:
        self._uow = uow_factory
        self._identity = identity
        self._workspace_id = workspace_id
        self._quota = quota
        self._resume = resume

    def report(self) -> UsageReport:
        quota, settings = self._quota.snapshot()
        with self._uow(self._workspace_id) as uow:
            grants = uow.usage.grants()
        by_step, rows = self._resume.waiting()
        return UsageReport(quota, grants, dict(by_step), rows, settings.announcement, None)

    def request_credits(self, user_id: str, step: UsageStep | None, note: str) -> None:
        """Ask the platform's admins for more. Recorded in the audit log, where the admin
        console's Overview finds it until it is answered."""
        text = " ".join(note.split())[:500]
        if not step and not text:
            raise InvalidInput("say which step needs more, or write a short note")
        with self._identity() as ids:
            ids.audit.record(
                "credits_requested",
                actor_user_id=user_id,
                workspace_id=self._workspace_id,
                target_type="workspace",
                target_id=self._workspace_id,
                note=text,
                data={"step": step.value if step else None},
            )
            ids.commit()
