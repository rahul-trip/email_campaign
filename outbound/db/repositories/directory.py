"""The verified lead directory (Phase 6g): what a workspace may read and add, and what the
platform folds and reviews.

Two classes, because they run as different database roles. ``DirectoryRepository`` is for a
workspace's unit of work (``outbound_app``): it reads served facts and inserts observations,
reports and removals; it cannot read who contributed or reported anything.
``DirectoryAdminRepository`` is for the platform role: folding, review, figures and deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from outbound.db.models import (
    CompanyRow,
    ContactEmailRow,
    ContactRow,
    DirectoryCompanyRow,
    DirectoryEmailRow,
    DirectoryFlagRow,
    DirectoryObservationRow,
    DirectoryPersonRow,
    DirectorySuppressionRow,
    ProviderCallRow,
)
from outbound.db.types import utcnow
from outbound.domain.directory import (
    CONTRIBUTABLE,
    DIRECTORY,
    RETENTION,
    DirectoryHit,
    month,
    person_key,
)
from outbound.domain.enums import (
    CallOutcome,
    DirectoryStatus,
    DirectoryTarget,
    EmploymentStatus,
    FlagStatus,
    Provenance,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.hashing import hash_value


class DirectoryRepository:
    """A workspace's view. ``outbound_app`` may SELECT the facts and INSERT the rest."""

    def __init__(self, session: Session, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    # ------------------------------------------------------------------ reading

    def find_email(
        self, domain: str, first_name: str, last_name: str, now: datetime
    ) -> DirectoryHit | None:
        """A served address for this person, or None. Skips anything disputed, expired, or
        removed on request."""
        first, last = person_key(first_name, last_name)
        stmt = (
            select(DirectoryEmailRow)
            .join(DirectoryPersonRow, DirectoryPersonRow.id == DirectoryEmailRow.person_id)
            .where(
                DirectoryPersonRow.company_domain == domain.lower(),
                DirectoryPersonRow.first_name == first,
                DirectoryPersonRow.last_name == last,
                DirectoryPersonRow.status == DirectoryStatus.VERIFIED,
                DirectoryPersonRow.employment_status != EmploymentStatus.LEFT,
                DirectoryEmailRow.status == DirectoryStatus.VERIFIED,
                DirectoryEmailRow.verified_at >= now - RETENTION,
            )
            .order_by(DirectoryEmailRow.verified_at.desc())
        )
        for row in self._session.scalars(stmt):
            if not self._blocked(row.email):
                return DirectoryHit(row.email, row.source, month(row.verified_at))
        return None

    def pattern(self, domain: str) -> str | None:
        stmt = select(DirectoryCompanyRow.email_pattern).where(
            DirectoryCompanyRow.domain == domain.lower(),
            DirectoryCompanyRow.status == DirectoryStatus.VERIFIED,
            DirectoryCompanyRow.pattern_confidence >= 1,
        )
        return self._session.scalars(stmt).first()

    def holds(self, email: str) -> bool:
        stmt = select(DirectoryEmailRow.id).where(DirectoryEmailRow.email == email.lower())
        return self._session.scalars(stmt).first() is not None

    def verified_month(self, email: str) -> str | None:
        """The month an address was last verified, if the directory holds it. Months only."""
        stmt = select(DirectoryEmailRow.verified_at).where(DirectoryEmailRow.email == email.lower())
        found = self._session.scalars(stmt).first()
        return month(found) if found else None

    def _blocked(self, email: str) -> bool:
        flagged = select(DirectoryFlagRow.target_key).where(
            DirectoryFlagRow.target_type == DirectoryTarget.EMAIL,
            DirectoryFlagRow.target_key == email,
            DirectoryFlagRow.status == FlagStatus.OPEN,
        )
        removed = select(DirectorySuppressionRow.value_hash).where(
            DirectorySuppressionRow.value_hash == hash_value(email)
        )
        return (
            self._session.scalars(flagged).first() is not None
            or self._session.scalars(removed).first() is not None
        )

    # ------------------------------------------------------------------ adding

    def observe_email(
        self,
        *,
        email: str,
        domain: str,
        first_name: str,
        last_name: str,
        full_name: str,
        title: str | None,
        provenance: str,
        source: str,
        verified_by: str | None,
        observed_at: datetime,
    ) -> None:
        self._observe(
            DirectoryTarget.EMAIL,
            email.lower(),
            {
                "domain": domain.lower(),
                "first_name": first_name,
                "last_name": last_name,
                "full_name": full_name,
                "title": title,
                "provenance": provenance,
                "verified_by": verified_by,
            },
            source,
            observed_at,
        )

    def observe_pattern(
        self, domain: str, pattern: str, source: str, observed_at: datetime
    ) -> None:
        self._observe(
            DirectoryTarget.PATTERN, domain.lower(), {"pattern": pattern}, source, observed_at
        )

    def _observe(
        self,
        target: DirectoryTarget,
        key: str,
        data: dict[str, Any],
        source: str,
        observed_at: datetime,
    ) -> None:
        self._session.add(
            DirectoryObservationRow(
                target_type=target,
                target_key=key,
                data=data,
                source=source,
                observed_at=observed_at,
                contributor_workspace_id=self._workspace_id,
            )
        )
        self._session.flush()

    def report(self, target: DirectoryTarget, key: str, field: str, reason: str) -> None:
        """A customer says a fact is wrong. It stops being served until staff resolve it."""
        self._session.add(
            DirectoryFlagRow(
                target_type=target,
                target_key=key.lower(),
                field=field,
                reason=reason[:500],
                reporter_workspace_id=self._workspace_id,
            )
        )
        self._session.flush()

    def backfill(self, since: datetime, *, dry_run: bool) -> int:
        """Share this workspace's verified addresses found since ``since`` (the alpha's start):
        the proven ones that are not the operator's own typing. Returns how many were (or
        would be) shared; observations already folded just refresh the same fact."""
        stmt = (
            select(ContactEmailRow, ContactRow, CompanyRow)
            .join(ContactRow, ContactRow.id == ContactEmailRow.contact_id)
            .join(CompanyRow, CompanyRow.id == ContactRow.company_id)
            .where(
                ContactEmailRow.workspace_id == self._workspace_id,
                ContactEmailRow.status.in_(CONTRIBUTABLE),
                ContactEmailRow.provenance != Provenance.OPERATOR_GIVEN,
                ContactEmailRow.email.is_not(None),
                ContactEmailRow.verified_at >= since,
                ContactRow.first_name.is_not(None),
                ContactRow.last_name.is_not(None),
            )
        )
        shared = 0
        for address, contact, company in self._session.execute(stmt):
            shared += 1
            if not dry_run:
                self.observe_email(
                    email=address.email or "",
                    domain=company.domain,
                    first_name=contact.first_name or "",
                    last_name=contact.last_name or "",
                    full_name=contact.full_name or "",
                    title=contact.title,
                    provenance=address.provenance.value,
                    source=address.found_by or address.provenance.value,
                    verified_by=address.verified_by,
                    observed_at=address.verified_at or since,
                )
        return shared

    def remove_person(self, email: str) -> None:
        """Forget: keep only a hash, so the person is never added again. Staff's next pass
        deletes what is held."""
        key = email.lower()
        self._session.execute(
            delete(DirectoryObservationRow).where(DirectoryObservationRow.target_key == key)
        )
        self._session.execute(delete(DirectoryFlagRow).where(DirectoryFlagRow.target_key == key))
        digest = hash_value(email)
        exists = self._session.scalars(
            select(DirectorySuppressionRow.value_hash).where(
                DirectorySuppressionRow.value_hash == digest
            )
        ).first()
        if exists is None:
            self._session.add(DirectorySuppressionRow(value_hash=digest, created_at=utcnow()))
            self._session.flush()


@dataclass(frozen=True)
class DirectoryFigures:
    companies: int
    people: int
    emails: int
    open_reports: int
    unfolded: int
    lookups: int  # this month
    hits: int
    saved_micro_usd: int


@dataclass(frozen=True)
class FlagView:
    id: str
    target_type: str
    target_key: str
    field: str
    reason: str
    created_at: datetime


class DirectoryAdminRepository:
    """The platform's view: apply what customers observed, review reports, count, delete."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------ folding

    def fold(self, now: datetime) -> dict[str, int]:
        """Apply every new observation to the served facts. Removed people are skipped; a fact
        confirmed wrong is not learned again."""
        removed = set(self._session.scalars(select(DirectorySuppressionRow.value_hash)))
        counts = {"emails": 0, "patterns": 0, "skipped": 0}
        stmt = (
            select(DirectoryObservationRow)
            .where(DirectoryObservationRow.folded_at.is_(None))
            .order_by(DirectoryObservationRow.observed_at)
        )
        for obs in list(self._session.scalars(stmt)):
            obs.folded_at = now
            if obs.target_type is DirectoryTarget.EMAIL:
                if hash_value(obs.target_key) in removed or not self._fold_email(obs):
                    counts["skipped"] += 1
                else:
                    counts["emails"] += 1
            elif obs.target_type is DirectoryTarget.PATTERN:
                self._fold_pattern(obs)
                counts["patterns"] += 1
            self._session.flush()
        return counts

    def _fold_email(self, obs: DirectoryObservationRow) -> bool:
        data = obs.data
        first, last = person_key(str(data["first_name"]), str(data["last_name"]))
        domain = str(data["domain"])
        person = self._session.scalars(
            select(DirectoryPersonRow).where(
                DirectoryPersonRow.company_domain == domain,
                DirectoryPersonRow.first_name == first,
                DirectoryPersonRow.last_name == last,
            )
        ).first()
        if person is None:
            person = DirectoryPersonRow(
                company_domain=domain,
                full_name=str(data.get("full_name") or f"{first} {last}"),
                first_name=first,
                last_name=last,
                title=data.get("title"),
                last_confirmed_at=obs.observed_at,
            )
            self._session.add(person)
            self._session.flush()
        else:
            person.last_confirmed_at = max(person.last_confirmed_at, obs.observed_at)
            if data.get("title"):
                person.title = data["title"]
        known = self._session.scalars(
            select(DirectoryEmailRow).where(DirectoryEmailRow.email == obs.target_key)
        ).first()
        if known is None:
            self._session.add(
                DirectoryEmailRow(
                    email=obs.target_key,
                    person_id=person.id,
                    provenance=str(data.get("provenance") or ""),
                    source=obs.source,
                    verified_by=data.get("verified_by"),
                    verified_at=obs.observed_at,
                )
            )
        elif known.status is DirectoryStatus.INVALID:
            return False  # confirmed wrong; not learned again
        else:
            known.verified_at = max(known.verified_at, obs.observed_at)
            known.verified_by = data.get("verified_by") or known.verified_by
        return True

    def _fold_pattern(self, obs: DirectoryObservationRow) -> None:
        pattern = str(obs.data["pattern"])
        company = self._session.scalars(
            select(DirectoryCompanyRow).where(DirectoryCompanyRow.domain == obs.target_key)
        ).first()
        if company is None:
            self._session.add(
                DirectoryCompanyRow(
                    domain=obs.target_key,
                    email_pattern=pattern,
                    pattern_confidence=1,
                    last_confirmed_at=obs.observed_at,
                )
            )
        elif company.email_pattern == pattern:
            company.pattern_confidence += 1
            company.last_confirmed_at = max(company.last_confirmed_at, obs.observed_at)
        elif company.pattern_confidence > 1:
            company.pattern_confidence -= 1  # a disagreement weakens it
        else:
            company.email_pattern, company.pattern_confidence = pattern, 1
            company.last_confirmed_at = obs.observed_at

    # ------------------------------------------------------------------ removal and expiry

    def remove_address(self, email: str) -> int:
        """Delete everything held about an address and never add it again (a person's own
        request). Returns how many addresses were deleted."""
        key = email.strip().lower()
        gone = self._session.execute(
            delete(DirectoryEmailRow).where(DirectoryEmailRow.email == key)
        )
        self._session.execute(
            delete(DirectoryObservationRow).where(DirectoryObservationRow.target_key == key)
        )
        self._session.execute(delete(DirectoryFlagRow).where(DirectoryFlagRow.target_key == key))
        digest = hash_value(key)
        if (
            self._session.scalars(
                select(DirectorySuppressionRow.value_hash).where(
                    DirectorySuppressionRow.value_hash == digest
                )
            ).first()
            is None
        ):
            self._session.add(DirectorySuppressionRow(value_hash=digest, created_at=utcnow()))
        self._session.flush()
        self._drop_orphans()
        return int(gone.rowcount or 0)  # type: ignore[attr-defined]

    def remove_suppressed(self) -> int:
        """Delete every held address (and a person with none left) that was asked to go."""
        removed = set(self._session.scalars(select(DirectorySuppressionRow.value_hash)))
        if not removed:
            return 0
        gone = 0
        for row in list(self._session.scalars(select(DirectoryEmailRow))):
            if hash_value(row.email) in removed:
                self._session.delete(row)
                gone += 1
        self._session.flush()
        self._drop_orphans()
        return gone

    def purge_expired(self, now: datetime) -> int:
        """Delete facts not confirmed again within the retention window."""
        result = self._session.execute(
            delete(DirectoryEmailRow).where(DirectoryEmailRow.verified_at < now - RETENTION)
        )
        self._session.flush()
        self._drop_orphans()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def _drop_orphans(self) -> None:
        with_email = select(DirectoryEmailRow.person_id)
        self._session.execute(
            delete(DirectoryPersonRow).where(DirectoryPersonRow.id.not_in(with_email))
        )
        self._session.flush()

    # ------------------------------------------------------------------ review

    def open_flags(self) -> list[FlagView]:
        stmt = (
            select(DirectoryFlagRow)
            .where(DirectoryFlagRow.status == FlagStatus.OPEN)
            .order_by(DirectoryFlagRow.created_at)
        )
        return [
            FlagView(f.id, f.target_type.value, f.target_key, f.field, f.reason, f.created_at)
            for f in self._session.scalars(stmt)
        ]

    def resolve(self, flag_id: str, *, accept: bool, note: str, now: datetime) -> None:
        """Staff decide a report. Accepted: the fact is wrong and is never served (or learned)
        again. Rejected: the report was wrong and the fact is served again."""
        flag = self._session.get(DirectoryFlagRow, flag_id)
        if flag is None or flag.status is not FlagStatus.OPEN:
            raise InvalidInput("that report was already decided, or does not exist")
        flag.status = FlagStatus.CONFIRMED if accept else FlagStatus.REJECTED
        flag.resolution, flag.resolved_at = note[:500], now
        if accept and flag.target_type is DirectoryTarget.EMAIL:
            email = self._session.scalars(
                select(DirectoryEmailRow).where(DirectoryEmailRow.email == flag.target_key)
            ).first()
            if email is not None:
                email.status = DirectoryStatus.INVALID
                if flag.field == "still_works":
                    person = self._session.get(DirectoryPersonRow, email.person_id)
                    if person is not None:
                        person.employment_status = EmploymentStatus.LEFT
        self._session.flush()

    # ------------------------------------------------------------------ figures

    def figures(
        self, start: datetime, end: datetime, finder_price_micro_usd: int
    ) -> DirectoryFigures:
        def count(table: Any, *where: Any) -> int:
            return int(
                self._session.scalar(select(func.count()).select_from(table).where(*where)) or 0
            )

        ledger = (
            ProviderCallRow.provider == DIRECTORY,
            ProviderCallRow.created_at >= start,
            ProviderCallRow.created_at < end,
        )
        hits = count(ProviderCallRow, *ledger, ProviderCallRow.outcome == CallOutcome.HIT)
        return DirectoryFigures(
            companies=count(DirectoryCompanyRow),
            people=count(DirectoryPersonRow),
            emails=count(DirectoryEmailRow),
            open_reports=count(DirectoryFlagRow, DirectoryFlagRow.status == FlagStatus.OPEN),
            unfolded=count(DirectoryObservationRow, DirectoryObservationRow.folded_at.is_(None)),
            lookups=count(ProviderCallRow, *ledger),
            hits=hits,
            saved_micro_usd=hits * finder_price_micro_usd,
        )

    def history(self, key: str) -> list[dict[str, Any]]:
        """What was observed about one address or domain: when, by which source. Never who."""
        stmt = (
            select(DirectoryObservationRow)
            .where(DirectoryObservationRow.target_key == key.lower())
            .order_by(DirectoryObservationRow.observed_at.desc())
            .limit(50)
        )
        return [
            {"at": o.observed_at, "target": o.target_type.value, "source": o.source}
            for o in self._session.scalars(stmt)
        ]

    def served_month(self, email: str) -> str | None:
        row = self._session.scalars(
            select(DirectoryEmailRow).where(DirectoryEmailRow.email == email.lower())
        ).first()
        return month(row.verified_at) if row else None
