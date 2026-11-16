"""Telling the people in a workspace what the engine did: drafts waiting, a hot lead, leads that
need them, a run that finished or failed, discovery paused, emails approved automatically.

The worker calls this after a run and after a tick. It writes a notification for every active
member of the workspace; the bell in the app reads them (``GET /api/me/notifications``). Quiet
passes write nothing, and a notice nobody has read yet is updated instead of repeated, so the
bell shows a few current lines, not a log. Nothing here is allowed to fail a run: the worker
wraps every call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import NotificationKind, UserStatus
from outbound.domain.qualification import is_hot
from outbound.logging import get_logger
from outbound.runner.tick import TickReport
from outbound.services.runs import RunService

log = get_logger(__name__)

KEEP = timedelta(days=90)
QUIET_PAUSED = timedelta(hours=24)  # "discovery is paused" is said at most once a day
_DRAFT_STATUS = "copy_ready"
_SCORED = ("qualified", "contacts_found", "email_ready", _DRAFT_STATUS)


class ActivityNotifier:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        identity: IdentityUnitOfWorkFactory,
        workspace: Callable[[str], tuple[str, str] | None],
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        """``workspace`` maps a workspace id to its (slug, name), or None when it is gone: the
        worker supplies it, because only it may read the platform's tables."""
        self._uow = uow_factory
        self._identity = identity
        self._workspace = workspace
        self._now = now

    # ------------------------------------------------------------------ after the worker's work

    def after_run(self, workspace_id: str, run_id: str, *, by_person: bool) -> None:
        """Say what a finished run did. A run started by a person always gets a line back, even
        an empty one; the engine's own runs say something only when there is something."""
        leads = RunService(self._uow, workspace_id).leads(run_id)
        drafts = [lead for lead in leads if any(s.to_status == _DRAFT_STATUS for s in lead.steps)]
        held = sum(1 for lead in leads if lead.outcome == "held")
        failed = sum(1 for lead in leads if lead.outcome == "failed")
        hot: list[tuple[str, str, int]] = []
        with self._uow(workspace_id) as uow:
            for lead in leads:
                if not any(s.to_status in _SCORED for s in lead.steps):
                    continue
                company = uow.companies.get(lead.company_id)
                if is_hot(company.fit_score):
                    hot.append((company.id, company.name or company.domain, company.fit_score or 0))
        if drafts:
            self._tell(
                workspace_id,
                NotificationKind.DRAFTS_READY,
                {"drafts": len(drafts), "hot": sum(1 for d in drafts if _is_in(d.company_id, hot))},
                add_up=("drafts", "hot"),
            )
        for company_id, name, score in hot:
            self._tell(
                workspace_id,
                NotificationKind.HOT_LEAD,
                {"company_id": company_id, "company": name, "fit": score},
                once=("company_id", company_id),
            )
        if held or failed:
            self._tell(
                workspace_id,
                NotificationKind.NEEDS_ATTENTION,
                {"held": held, "failed": failed},
                add_up=("held", "failed"),
            )
        if by_person:
            self._tell(
                workspace_id,
                NotificationKind.RUN_FINISHED,
                {"run_id": run_id, "drafts": len(drafts), "moved": len(leads)},
            )

    def after_tick(self, workspace_id: str, report: TickReport) -> None:
        if report.pipeline is not None:
            self.after_run(workspace_id, report.pipeline.run_id, by_person=False)
        approved = report.jobs.get("auto_approve", {}).get("approved", 0)
        if approved:
            self._tell(
                workspace_id,
                NotificationKind.AUTO_APPROVED,
                {"approved": approved},
                add_up=("approved",),
            )

    def run_failed(self, workspace_id: str, run_id: str, reason: str) -> None:
        self._tell(
            workspace_id,
            NotificationKind.RUN_FAILED,
            {"run_id": run_id, "reason": reason[:200]},
        )

    def discovery_paused(self, workspace_id: str, waiting: int, limit: int) -> None:
        self._tell(
            workspace_id,
            NotificationKind.DISCOVERY_PAUSED,
            {"waiting": waiting, "limit": limit},
            quiet_since=self._now() - QUIET_PAUSED,
        )

    def prune(self) -> int:
        """Forget notifications older than 90 days (a periodic job of the worker)."""
        with self._identity() as ids:
            removed = ids.notifications.prune(self._now() - KEEP)
            ids.commit()
        return removed

    # ------------------------------------------------------------------ writing

    def _tell(
        self,
        workspace_id: str,
        kind: NotificationKind,
        data: dict[str, Any],
        *,
        add_up: tuple[str, ...] = (),
        once: tuple[str, str] | None = None,
        quiet_since: datetime | None = None,
    ) -> None:
        found = self._workspace(workspace_id)
        if found is None:
            return
        body = {"slug": found[0], "workspace_name": found[1], **data}
        with self._identity() as ids:
            for _, user in ids.memberships.members(workspace_id):
                if user.status is not UserStatus.ACTIVE:
                    continue
                ids.notifications.upsert_unread(
                    user.id,
                    kind,
                    workspace_id=workspace_id,
                    data=body,
                    add_up=add_up,
                    once=once,
                    quiet_since=quiet_since,
                )
            ids.commit()
        log.debug("activity_notice", workspace_id=workspace_id, kind=kind.value)


def _is_in(company_id: str, hot: list[tuple[str, str, int]]) -> bool:
    return any(h[0] == company_id for h in hot)
