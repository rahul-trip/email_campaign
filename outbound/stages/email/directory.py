"""The free first link of the email waterfall: the shared verified lead directory (Phase 6g).

It answers like a finder, so the waterfall needs no special case: an address another customer's
run already verified, or nothing. The waterfall still verifies what it returns, once, which is
the small re-check a stale fact needs and costs far less than a finder lookup. Nothing it
returns says who contributed the address or when it was looked up.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.directory import DIRECTORY
from outbound.providers.ports import FinderResult, PersonQuery


class DirectoryFinder:
    name = DIRECTORY

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

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        with self._uow(self._workspace_id) as uow:
            hit = uow.directory.find_email(domain, person.first_name, person.last_name, self._now())
        return FinderResult(
            email=hit.email if hit else None,
            provider=DIRECTORY,
            confidence=0.9 if hit else None,
            raw_status="hit" if hit else "miss",
            billed=False,
        )
