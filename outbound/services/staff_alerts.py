"""Alerts for the platform's own staff, in the admin console's bell.

Used when something needs a person on the platform side: a vendor key refused or out of credit, a
run or a worker pass that crashed, a server error. Each alert has a ``key``; a staff member gets
one notice per key, so a key that carries the day (or the hour) is repeated at most that often.
Raising an alert never fails the caller: it is logged and dropped if it cannot be written.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.types import utcnow
from outbound.domain.enums import NotificationKind, UserStatus
from outbound.logging import get_logger

log = get_logger(__name__)


class StaffAlerts:
    def __init__(
        self, identity: IdentityUnitOfWorkFactory, *, now: Callable[[], datetime] = utcnow
    ) -> None:
        self._identity = identity
        self._now = now

    def alert(self, key: str, title: str, text: str, *, link: str = "/admin") -> int:
        """One notice per staff member for this ``key``; returns how many were written."""
        try:
            written = 0
            with self._identity() as ids:
                for user in ids.users.all():
                    if not user.platform_role or user.status is not UserStatus.ACTIVE:
                        continue
                    written += ids.notifications.upsert_unread(
                        user.id,
                        NotificationKind.PLATFORM_ALERT,
                        workspace_id=None,
                        data={"key": key, "title": title, "text": text[:500], "link": link},
                        once=("key", key),
                    )
                ids.commit()
            return written
        except Exception as error:  # noqa: BLE001 — an alert must never break what raised it
            log.warning("staff_alert_failed", key=key[:120], error_type=type(error).__name__)
            return 0

    def error(self, where: str, error: BaseException, *, detail: str = "") -> int:
        """A crash staff should look at: at most one notice an hour per place and error type."""
        kind = type(error).__name__
        hour = f"{self._now():%Y-%m-%dT%H}"
        text = f"{kind} in {where}." + (f" {detail}" if detail else "")
        return self.alert(
            f"error:{where}:{kind}:{hour}",
            f"Something broke: {where}",
            text + " The details are in the server log.",
        )
