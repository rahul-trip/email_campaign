"""The verified lead directory, from both sides (Phase 6g).

``LeadDirectory`` is a workspace's: report a wrong detail on a lead, and choose to find a lead's
email with the vendors instead of the directory (an ability an admin gives each customer).
``DirectoryService`` is the platform's: fold what runs observed into served facts, delete what
was removed or expired, decide reports, and report the figures. Both keep every fact free of
who contributed it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.repositories.directory import DirectoryFigures, FlagView
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.enums import DirectoryTarget, EmailStatus
from outbound.domain.errors import InvalidInput
from outbound.domain.state_machines import EMAIL
from outbound.logging import get_logger
from outbound.metering.quota import quota_in

log = get_logger(__name__)


def finder_price(settings: Settings) -> int:
    """What one lookup at the first paid finder costs: what each directory hit saves."""
    from outbound.providers.pricing import DEFAULT_PRICES, price_of

    first = settings.finder_chain[0] if settings.finder_chain else ""
    return price_of({**DEFAULT_PRICES, **settings.provider_prices}, first, "find")


REPORT_FIELDS = ("email", "still_works", "title", "linkedin", "company_name", "country")


@dataclass(frozen=True)
class DirectoryBadge:
    """What a lead page may show about a directory-backed address."""

    in_directory: bool
    verified_month: str | None
    can_skip: bool
    skipping: bool


class LeadDirectory:
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

    def badge(self, company_id: str) -> DirectoryBadge:
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            quota, _ = quota_in(uow, self._now())
            address = self._primary(uow, company_id)
            verified = uow.directory.verified_month(address) if address else None
        return DirectoryBadge(
            verified is not None,
            verified,
            quota.entitlements.has("directory_bypass"),
            company.skip_directory,
        )

    def report(self, company_id: str, field: str, reason: str) -> None:
        """Say a detail about this lead's person is wrong. The directory stops serving the
        address until staff decide, and this workspace stops using it too (an address you
        called wrong is marked invalid here)."""
        if field not in REPORT_FIELDS:
            raise InvalidInput(f"choose one of: {', '.join(REPORT_FIELDS)}")
        with self._uow(self._workspace_id) as uow:
            address = self._primary(uow, company_id)
            if address is None or not uow.directory.holds(address):
                raise InvalidInput("the directory holds nothing about this lead's person")
            target = (
                DirectoryTarget.EMAIL
                if field in ("email", "still_works")
                else DirectoryTarget.PERSON
            )
            uow.directory.report(target, address, field, reason)
            # This workspace stops using the address at once; the engine looks for another.
            if field in ("email", "still_works"):
                held = uow.emails.by_address(address)
                if held is not None and EMAIL.allows(held.status, EmailStatus.INVALID):
                    uow.emails.transition(held.id, EmailStatus.INVALID, actor=OPERATOR)
            uow.commit()
        log.info("directory_reported", company_id=company_id, field=field)

    def skip(self, company_id: str, skip: bool, *, actor: str = OPERATOR) -> None:
        """Find this lead's emails with the vendors (needs the ``directory_bypass`` ability)."""
        with self._uow(self._workspace_id) as uow:
            quota, _ = quota_in(uow, self._now())
            if skip and not quota.entitlements.has("directory_bypass"):
                raise InvalidInput("your plan does not include skipping the directory")
            uow.companies.set_skip_directory(company_id, skip, actor=actor)
            uow.commit()

    @staticmethod
    def _primary(uow: UnitOfWork, company_id: str) -> str | None:
        for contact in uow.contacts.for_company(company_id):
            for address in uow.emails.for_contact(contact.id):
                if address.is_primary and address.email:
                    return address.email
        return None


@dataclass(frozen=True)
class DirectoryOverview:
    figures: DirectoryFigures
    flags: list[FlagView]


class DirectoryService:
    name = "directory"

    def __init__(
        self,
        platform: PlatformUnitOfWorkFactory,
        *,
        finder_price_micro_usd: int,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._platform = platform
        self._finder_price = finder_price_micro_usd  # what one finder lookup would have cost
        self._now = now

    def run(self) -> dict[str, int]:
        """The platform's pass: fold, delete what was removed or expired."""
        now = self._now()
        with self._platform() as p:
            counts = p.directory.fold(now)
            counts["removed"] = p.directory.remove_suppressed()
            counts["expired"] = p.directory.purge_expired(now)
            p.commit()
        if any(counts.values()):
            log.info("directory_folded", **counts)
        return counts

    def overview(self) -> DirectoryOverview:
        now = self._now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self._platform() as p:
            return DirectoryOverview(
                p.directory.figures(start, start + timedelta(days=32), self._finder_price),
                p.directory.open_flags(),
            )

    def resolve(self, flag_id: str, *, accept: bool, note: str, by: str) -> None:
        with self._platform() as p:
            p.directory.resolve(flag_id, accept=accept, note=note, now=self._now())
            p.audit.record(
                "directory_report_accepted" if accept else "directory_report_rejected",
                actor_user_id=by,
                target_type="directory_flag",
                target_id=flag_id,
                note=note or None,
            )
            p.commit()

    def history(self, key: str) -> list[dict[str, object]]:
        with self._platform() as p:
            return list(p.directory.history(key))
