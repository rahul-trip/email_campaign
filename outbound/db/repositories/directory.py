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
class EntryView:
    """One address in the directory with the person it belongs to, for staff to browse."""

    id: str  # the address row
    email: str
    status: str
    provenance: str
    source: str
    verified_at: datetime
    person_id: str
    full_name: str
    first_name: str
    last_name: str
    title: str | None
    linkedin_url: str | None
    company_domain: str
    employment_status: str


@dataclass(frozen=True)
class CompanyView:
    id: str
    domain: str
    name: str | None
    country_code: str | None
    email_pattern: str | None
    pattern_confidence: int
    status: str


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

    # ------------------------------------------------------------------ browse and edit

    def entries(self, q: str, limit: int, offset: int) -> tuple[list[EntryView], int]:
        """Addresses with their people, newest verification first; ``q`` matches the address,
        the name or the company's domain."""
        stmt = select(DirectoryEmailRow, DirectoryPersonRow).join(
            DirectoryPersonRow, DirectoryPersonRow.id == DirectoryEmailRow.person_id
        )
        needle = q.strip().lower()
        if needle:
            like = f"%{needle}%"
            stmt = stmt.where(
                func.lower(DirectoryEmailRow.email).like(like)
                | func.lower(DirectoryPersonRow.full_name).like(like)
                | func.lower(DirectoryPersonRow.company_domain).like(like)
            )
        total = int(self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = self._session.execute(
            stmt.order_by(DirectoryEmailRow.verified_at.desc()).limit(limit).offset(offset)
        )
        return [_entry(e, p) for e, p in rows], total

    def entry(self, email_id: str) -> EntryView:
        row = self._session.execute(
            select(DirectoryEmailRow, DirectoryPersonRow)
            .join(DirectoryPersonRow, DirectoryPersonRow.id == DirectoryEmailRow.person_id)
            .where(DirectoryEmailRow.id == email_id)
        ).first()
        if row is None:
            raise InvalidInput("that directory entry does not exist")
        return _entry(*row)

    def add_entry(
        self,
        *,
        email: str,
        first_name: str,
        last_name: str,
        company_domain: str,
        title: str | None,
        linkedin_url: str | None,
        now: datetime,
    ) -> EntryView:
        """A person and address added by hand, served like any verified fact."""
        address = email.strip().lower()
        if "@" not in address:
            raise InvalidInput("give a full email address")
        if self._session.scalars(
            select(DirectorySuppressionRow.value_hash).where(
                DirectorySuppressionRow.value_hash == hash_value(address)
            )
        ).first():
            raise InvalidInput("this person asked to be removed and cannot be added again")
        if self._session.scalars(
            select(DirectoryEmailRow.id).where(DirectoryEmailRow.email == address)
        ).first():
            raise InvalidInput("that address is already in the directory")
        first, last = person_key(first_name, last_name)
        if not (first and last):
            raise InvalidInput("a first and a last name are needed")
        domain = company_domain.strip().lower()
        if "." not in domain:
            raise InvalidInput("give the company's domain, for example acme.com")
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
                full_name=f"{first_name.strip()} {last_name.strip()}",
                first_name=first,
                last_name=last,
                title=(title or None),
                linkedin_url=(linkedin_url or None),
                last_confirmed_at=now,
            )
            self._session.add(person)
            self._session.flush()
        row = DirectoryEmailRow(
            email=address, person_id=person.id, provenance="staff", source="staff",
            verified_at=now,
        )  # fmt: skip
        self._session.add(row)
        self._session.flush()
        return _entry(row, person)

    def update_entry(self, email_id: str, changes: dict[str, Any], now: datetime) -> EntryView:
        """Change an entry's address, status, or its person's details."""
        row = self._session.get(DirectoryEmailRow, email_id)
        if row is None:
            raise InvalidInput("that directory entry does not exist")
        person = self._session.get(DirectoryPersonRow, row.person_id)
        if person is None:  # cannot happen: the address has a person (a foreign key)
            raise InvalidInput("that directory entry has no person")
        if changes.get("email"):
            address = str(changes["email"]).strip().lower()
            taken = self._session.scalars(
                select(DirectoryEmailRow.id).where(
                    DirectoryEmailRow.email == address, DirectoryEmailRow.id != email_id
                )
            ).first()
            if "@" not in address or taken:
                raise InvalidInput("that address is not valid or is already in the directory")
            row.email = address
        if changes.get("status"):
            row.status = DirectoryStatus(changes["status"])
        if changes.get("employment_status"):
            person.employment_status = EmploymentStatus(changes["employment_status"])
        for name in ("title", "linkedin_url"):
            if name in changes:
                setattr(person, name, changes[name] or None)
        for name in ("first_name", "last_name"):
            if changes.get(name):
                setattr(person, name, person_key(str(changes[name]), "x")[0])
        if changes.get("first_name") or changes.get("last_name"):
            person.full_name = f"{changes.get('first_name') or person.first_name} " + (
                str(changes.get("last_name") or person.last_name)
            )
        row.verified_at = now  # staff looked at it
        self._session.flush()
        return _entry(row, person)

    def delete_entry(self, email_id: str, *, block: bool) -> str:
        """Remove an address (and its person if it was their last). With ``block`` it is also
        never added again. Returns the address that was removed."""
        row = self._session.get(DirectoryEmailRow, email_id)
        if row is None:
            raise InvalidInput("that directory entry does not exist")
        address = row.email
        if block:
            self.remove_address(address)
        else:
            self._session.delete(row)
            self._session.execute(
                delete(DirectoryObservationRow).where(DirectoryObservationRow.target_key == address)
            )
            self._session.flush()
            self._drop_orphans()
        return address

    def companies(self, q: str, limit: int, offset: int) -> tuple[list[CompanyView], int]:
        stmt = select(DirectoryCompanyRow)
        if q.strip():
            stmt = stmt.where(func.lower(DirectoryCompanyRow.domain).like(f"%{q.strip().lower()}%"))
        total = int(self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = self._session.scalars(
            stmt.order_by(DirectoryCompanyRow.domain).limit(limit).offset(offset)
        )
        return [_company(c) for c in rows], total

    def save_company(
        self,
        domain: str,
        *,
        name: str | None,
        country_code: str | None,
        email_pattern: str | None,
        now: datetime,
    ) -> CompanyView:
        """Add a company, or change what the directory knows about it."""
        key = domain.strip().lower()
        if "." not in key:
            raise InvalidInput("give the company's domain, for example acme.com")
        row = self._session.scalars(
            select(DirectoryCompanyRow).where(DirectoryCompanyRow.domain == key)
        ).first()
        if row is None:
            row = DirectoryCompanyRow(domain=key, last_confirmed_at=now, pattern_confidence=0)
            self._session.add(row)
        row.name = name or None
        row.country_code = (country_code or "").upper() or None
        if (email_pattern or None) != row.email_pattern:
            row.email_pattern = email_pattern or None
            row.pattern_confidence = 3 if email_pattern else 0  # a staff pattern is trusted
        row.last_confirmed_at = now
        self._session.flush()
        return _company(row)

    def delete_company(self, domain: str) -> None:
        key = domain.strip().lower()
        self._session.execute(delete(DirectoryCompanyRow).where(DirectoryCompanyRow.domain == key))
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


def _entry(e: DirectoryEmailRow, p: DirectoryPersonRow) -> EntryView:
    return EntryView(
        e.id, e.email, e.status.value, e.provenance, e.source, e.verified_at, p.id,
        p.full_name, p.first_name, p.last_name, p.title, p.linkedin_url, p.company_domain,
        p.employment_status.value,
    )  # fmt: skip


def _company(c: DirectoryCompanyRow) -> CompanyView:
    return CompanyView(
        c.id, c.domain, c.name, c.country_code, c.email_pattern, c.pattern_confidence,
        c.status.value,
    )  # fmt: skip
