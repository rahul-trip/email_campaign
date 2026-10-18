"""Tick job: collect answers from the asynchronous catch-all resolver.

For each company held as ``catch_all_resolving`` whose wake-up time has come, ask the resolver
about its pending address. An answer settles the address and releases the company to
``contacts_found``, where the email stage runs again and either uses the resolved address or
moves on to the next contact. No answer yet means look again later. Polling is free.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.enums import CompanyStatus, EmailStatus, HoldReason
from outbound.domain.state_machines import resume_status_for
from outbound.logging import get_logger
from outbound.providers.ports import CatchAllResolver, ResolutionStatus, ResolutionTicket
from outbound.stages.email.stage import POLL_DELAY

log = get_logger(__name__)

_OUTCOME = {
    ResolutionStatus.VALID: EmailStatus.CATCH_ALL_RESOLVED,
    ResolutionStatus.INVALID: EmailStatus.INVALID,
    ResolutionStatus.UNRESOLVED: EmailStatus.CATCH_ALL_UNVERIFIED,
}


class CatchAllPoller:
    name = "catch_all_poll"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        resolver: CatchAllResolver,
        *,
        delay: timedelta = POLL_DELAY,
        limit: int = 50,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._resolver = resolver
        self._delay = delay
        self._limit = limit
        self._now = now

    def run(self) -> dict[str, int]:
        counts = {"checked": 0, "released": 0, "still_waiting": 0, "errors": 0}
        moment: datetime = self._now()
        with self._uow(self._workspace_id) as uow:
            waiting = uow.companies.due_held(HoldReason.CATCH_ALL_RESOLVING, self._limit, moment)
        for company in waiting:
            counts["checked"] += 1
            try:
                released = self._poll_company(company.id, moment)
            except Exception:  # one bad lead must not stop the rest
                log.exception("catch_all_poll_failed", company_id=company.id)
                counts["errors"] += 1
                continue
            counts["released" if released else "still_waiting"] += 1
        return counts

    def _poll_company(self, company_id: str, moment: datetime) -> bool:
        with self._uow(self._workspace_id) as uow:
            pending = uow.emails.pending_for_company(company_id)
        answers = []
        for email in pending:
            if email.email and email.resolution_ref:
                ticket = ResolutionTicket(
                    ref=email.resolution_ref,
                    email=email.email,
                    provider=email.verified_by or self._resolver.name,
                )
                answers.append((email, self._resolver.poll(ticket)))

        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.status is not CompanyStatus.HELD:
                return False
            settled = False
            for email, result in answers:
                if result is None:
                    continue
                uow.emails.transition(
                    email.id, _OUTCOME[result.status], verified_by=result.provider, actor=SYSTEM
                )
                settled = True
            if pending and not settled:  # the resolver has not answered yet
                uow.companies.update_fields(
                    company_id,
                    {"next_action_at": moment + self._delay},
                    actor=SYSTEM,
                    expected_version=company.row_version,
                )
                uow.commit()
                return False
            target = (
                resume_status_for(HoldReason.CATCH_ALL_RESOLVING) or CompanyStatus.CONTACTS_FOUND
            )
            uow.companies.transition(
                company_id,
                target,
                expected_version=company.row_version,
                reason="catch-all answer received" if settled else "nothing pending; resuming",
                next_action_at=None,
            )
            uow.commit()
            return True
