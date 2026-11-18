"""Emails the platform sends about AI credits and access (Phase 6d.8).

One periodic pass (``run``, from the worker's tick) finds what deserves a notice and sends each
once. "Once" is the audit log: every notice sent leaves a ``notice_sent`` row whose key names it,
so a restart or a second worker never repeats one. Workspace admins hear about their own
allowance; platform staff hear about credit requests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.types import utcnow
from outbound.domain.enums import MembershipRole, NotificationKind, UserStatus
from outbound.logging import get_logger
from outbound.providers.errors import ProviderError
from outbound.providers.ports import OutgoingEmail, TransactionalEmail
from outbound.services.admin import AdminService
from outbound.services.staff_alerts import StaffAlerts

log = get_logger(__name__)

SOON = timedelta(days=7)
LOOKBACK = timedelta(days=3)  # grants and requests older than this are not announced late
WARN_AT = 0.8
FAILING_AT = 3  # refused calls in a day before staff are told


class NoticeService:
    name = "notices"

    def __init__(
        self,
        admin: AdminService,
        identity: IdentityUnitOfWorkFactory,
        email: TransactionalEmail,
        app_base_url: str,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._admin = admin
        self._alerts = StaffAlerts(identity, now=now)
        self._identity = identity
        self._email = email
        self._base = app_base_url.rstrip("/")
        self._now = now

    def run(self) -> dict[str, int]:
        sent = {"workspace": 0, "staff": 0}
        now = self._now()
        for row in self._admin.customers():
            ws, quota = row.workspace, row.quota
            period = f"{quota.period_start:%Y-%m}"
            allowance, used = quota.credits.allowance, quota.credits.used_milli / 1000
            if allowance:
                level = 100 if used >= allowance else 80 if used >= allowance * WARN_AT else 0
                key = f"credits:{level}:{period}"
                if level and self._once(ws.id, key):
                    text = (
                        f"You have used all {allowance:,} of your AI credits this month."
                        if level == 100
                        else f"You have used {used:,.0f} of your {allowance:,} AI credits "
                        "this month."
                    )
                    sent["workspace"] += self._to_admins(
                        ws.id, f"{ws.name}: AI credits at {level}%", self._ask(text)
                    )
                    self._bell(ws.id, ws.slug, ws.name, text, key)
            if quota.access_until:
                day = f"{quota.access_until:%Y-%m-%d}"
                if quota.access_until <= now:
                    kind, text = (
                        "access_ended",
                        "Your access has ended. Your data is kept and can be read.",
                    )
                elif quota.access_until <= now + SOON:
                    kind, text = "access_ending", f"Your access ends on {day}."
                else:
                    kind = ""
                if kind and self._once(ws.id, f"{kind}:{day}"):
                    sent["workspace"] += self._to_admins(
                        ws.id, f"{ws.name}: {text.split('.')[0].lower()}", self._ask(text)
                    )
                    self._bell(ws.id, ws.slug, ws.name, text, f"{kind}:{day}")
            sent["workspace"] += self._grants(ws.id, ws.name, now)
        sent["staff"] += self._requests(now) + self._failing_keys(now)
        if any(sent.values()):
            log.info("notices_sent", **sent)
        return sent

    # ------------------------------------------------------------------ the kinds

    def _grants(self, workspace_id: str, name: str, now: datetime) -> int:
        with self._identity() as ids:
            grants = ids.audit.recent(
                workspace_id=workspace_id, action="credits_granted", since=now - LOOKBACK
            )
        count = 0
        for grant in grants:
            if self._once(workspace_id, f"grant:{grant['id']}"):
                data = grant["data"]
                count += self._to_admins(
                    workspace_id,
                    f"{name}: {data.get('amount')} AI credits added",
                    f"{data.get('amount')} extra AI credits were added to {name}."
                    f"\n\n{self._open()}",
                )
        return count

    def _requests(self, now: datetime) -> int:
        with self._identity() as ids:
            asks = ids.audit.recent(action="credits_requested", since=now - LOOKBACK, limit=100)
        count = 0
        for ask in asks:
            if self._once(ask["workspace_id"], f"request:{ask['id']}"):
                count += self.to_staff(
                    "A customer asked for more credits",
                    f"{ask['note'] or 'No note.'}\n\nOpen the admin console: {self._base}/admin",
                    key=f"request:{ask['id']}",
                )
        return count

    def _failing_keys(self, now: datetime) -> int:
        """A vendor that keeps refusing our key, or says our account is out of credit: staff
        hear once a day until it is fixed."""
        count = 0
        day = f"{now:%Y-%m-%d}"
        since = now - timedelta(days=1)
        for vendor, refused in self._admin.key_refusals(since).items():
            if refused >= FAILING_AT and self._once(None, f"keyfail:{vendor}:{day}"):
                count += self.to_staff(
                    f"The {vendor} key is being refused",
                    f"{refused} calls in the last day were rejected for a bad key. Replace it in "
                    f"the admin console, under Vendors and keys: {self._base}/admin/vendors",
                    key=f"keyfail:{vendor}:{day}",
                    link="/admin/vendors",
                )
        for vendor, refused in self._admin.key_refusals(since, "BudgetExceeded").items():
            if self._once(None, f"nocredit:{vendor}:{day}"):
                count += self.to_staff(
                    f"{vendor} is out of credit",
                    f"{refused} calls in the last day were refused because the {vendor} account "
                    "ran out of credit or reached its plan limit. Top it up, or add another key "
                    f"under Vendors and keys: {self._base}/admin/vendors",
                    key=f"nocredit:{vendor}:{day}",
                    link="/admin/vendors",
                )
        return count

    # ------------------------------------------------------------------ helpers

    def _ask(self, text: str) -> str:
        return f"{text}\n\nPlan and usage: {self._base}/"

    def _open(self) -> str:
        return f"Open the app: {self._base}/"

    def _once(self, workspace_id: str | None, key: str) -> bool:
        """Claim the notice ``key``; false when it was already sent."""
        with self._identity() as ids:
            done = [
                e
                for e in ids.audit.recent(
                    workspace_id=workspace_id, action="notice_sent", limit=500
                )
                if e["data"].get("key") == key
            ]
            if done:
                return False
            ids.audit.record(
                "notice_sent", actor_user_id=None, workspace_id=workspace_id, data={"key": key}
            )
            ids.commit()
        return True

    def _bell(self, workspace_id: str, slug: str, name: str, text: str, key: str) -> None:
        """The same notice in the app's bell, once, for each admin of the workspace."""
        with self._identity() as ids:
            for member, user in ids.memberships.members(workspace_id):
                if member.role is MembershipRole.ADMIN and user.status is UserStatus.ACTIVE:
                    ids.notifications.upsert_unread(
                        user.id,
                        NotificationKind.ACCOUNT,
                        workspace_id=workspace_id,
                        data={"slug": slug, "workspace_name": name, "text": text, "key": key},
                        once=("key", key),
                    )
            ids.commit()

    def _to_admins(self, workspace_id: str, subject: str, text: str) -> int:
        with self._identity() as ids:
            people = [
                user.email
                for m, user in ids.memberships.members(workspace_id)
                if m.role is MembershipRole.ADMIN and user.status is UserStatus.ACTIVE
            ]
        return self._send(people, subject, text)

    def to_staff(self, subject: str, text: str, *, key: str, link: str = "/admin") -> int:
        """Email every active staff member, and put it in the admin console's bell."""
        self._alerts.alert(key, subject, text, link=link)
        with self._identity() as ids:
            people = [
                u.email
                for u in ids.users.all()
                if u.platform_role and u.status is UserStatus.ACTIVE
            ]
        return self._send(people, subject, text)

    def _send(self, addresses: list[str], subject: str, text: str) -> int:
        sent = 0
        for address in addresses:
            try:
                self._email.send(OutgoingEmail(to=address, subject=subject, text=text))
                sent += 1
            except ProviderError:
                log.warning("notice_failed", subject=subject)
        return sent
