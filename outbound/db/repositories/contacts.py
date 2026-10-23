"""People: contacts, their email addresses, notes and consents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from outbound.db.models import ConsentRow, ContactEmailRow, ContactRow, NoteRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.db.types import utcnow
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Consent, Contact, ContactEmail, Note
from outbound.domain.enums import (
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EmailStatus,
    EntityType,
    NoteSource,
    Provenance,
)
from outbound.domain.state_machines import CONTACT, EMAIL

CONTACT_EDITABLE = frozenset(
    {"full_name", "first_name", "last_name", "title", "seniority", "linkedin_url", "rank"}
)


class ContactRepository(ScopedRepository):
    def add(
        self,
        company_id: str,
        *,
        rank: int,
        source: ContactSource,
        full_name: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        title: str | None = None,
        seniority: str | None = None,
        linkedin_url: str | None = None,
        status: ContactStatus = ContactStatus.CANDIDATE,
        actor: str = SYSTEM,
    ) -> Contact:
        row = ContactRow(
            workspace_id=self._workspace_id,
            company_id=company_id,
            rank=rank,
            source=source,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            title=title,
            seniority=seniority,
            linkedin_url=linkedin_url,
            status=status,
            manual_fields=[],
        )
        self._session.add(row)
        self._session.flush()
        self._events.append(
            EntityType.CONTACT, row.id, "created", actor, {"source": source.value, "rank": rank}
        )
        return snapshot(row, Contact)

    def get(self, contact_id: str) -> Contact:
        return snapshot(self._row(ContactRow, contact_id), Contact)

    def linkedin_taken(self, linkedin_url: str) -> bool:
        """Whether some contact in this workspace already holds that profile (it is unique)."""
        stmt = select(ContactRow.id).where(
            ContactRow.workspace_id == self._workspace_id, ContactRow.linkedin_url == linkedin_url
        )
        return self._session.scalars(stmt).first() is not None

    def for_company(self, company_id: str) -> list[Contact]:
        stmt = (
            select(ContactRow)
            .where(
                ContactRow.workspace_id == self._workspace_id, ContactRow.company_id == company_id
            )
            .order_by(ContactRow.rank, ContactRow.id)
        )
        return [snapshot(row, Contact) for row in self._session.scalars(stmt)]

    def transition(
        self, contact_id: str, to: ContactStatus, *, actor: str = SYSTEM, reason: str | None = None
    ) -> Contact:
        row = self._row(ContactRow, contact_id)
        CONTACT.check(row.status, to)
        previous = row.status
        row.status = to
        self._flush()
        detail: dict[str, Any] = {"from": previous.value, "to": to.value}
        if reason:
            detail["reason"] = reason
        self._events.append(EntityType.CONTACT, row.id, "status_changed", actor, detail)
        return snapshot(row, Contact)

    def make_first(self, contact_id: str) -> None:
        """Put one person at rank 1 and move the others down, keeping their order.

        Written as the engine, so the contacts stage may still re-rank later: what keeps the
        operator's person first is ``rank_contacts`` reading who they chose, not a frozen rank.
        """
        chosen = self._row(ContactRow, contact_id)
        others = [c.id for c in self.for_company(chosen.company_id) if c.id != contact_id]
        for position, contact in enumerate([contact_id, *others], start=1):
            self._apply_changes(
                self._row(ContactRow, contact),
                {"rank": position},
                editable=CONTACT_EDITABLE,
                actor=SYSTEM,
                entity_type=EntityType.CONTACT,
            )
        self._flush()

    def update_fields(self, contact_id: str, changes: Mapping[str, Any], *, actor: str) -> Contact:
        row = self._row(ContactRow, contact_id)
        self._apply_changes(
            row, changes, editable=CONTACT_EDITABLE, actor=actor, entity_type=EntityType.CONTACT
        )
        self._flush()
        return snapshot(row, Contact)


class ContactEmailRepository(ScopedRepository):
    def add(
        self,
        contact_id: str,
        email: str,
        provenance: Provenance,
        *,
        found_by: str | None = None,
        status: EmailStatus = EmailStatus.UNVERIFIED,
        is_primary: bool = False,
        verified_by: str | None = None,
        resolution_ref: str | None = None,
        actor: str = SYSTEM,
    ) -> ContactEmail:
        if is_primary:
            self._clear_primary(contact_id)
        row = ContactEmailRow(
            workspace_id=self._workspace_id,
            contact_id=contact_id,
            email=email.strip().lower(),
            provenance=provenance,
            found_by=found_by,
            status=status,
            is_primary=is_primary,
            verified_by=verified_by,
            verified_at=utcnow() if verified_by else None,
            resolution_ref=resolution_ref,
        )
        self._session.add(row)
        self._session.flush()
        self._events.append(
            EntityType.CONTACT_EMAIL,
            row.id,
            "created",
            actor,
            {"provenance": provenance.value, "found_by": found_by},
        )
        return snapshot(row, ContactEmail)

    def get(self, email_id: str) -> ContactEmail:
        return snapshot(self._row(ContactEmailRow, email_id), ContactEmail)

    def by_address(self, email: str) -> ContactEmail | None:
        stmt = select(ContactEmailRow).where(
            ContactEmailRow.workspace_id == self._workspace_id,
            ContactEmailRow.email == email.strip().lower(),
        )
        row = self._session.scalars(stmt).one_or_none()
        return snapshot(row, ContactEmail) if row else None

    def for_contact(self, contact_id: str) -> list[ContactEmail]:
        stmt = (
            select(ContactEmailRow)
            .where(
                ContactEmailRow.workspace_id == self._workspace_id,
                ContactEmailRow.contact_id == contact_id,
            )
            .order_by(ContactEmailRow.is_primary.desc(), ContactEmailRow.created_at)
        )
        return [snapshot(row, ContactEmail) for row in self._session.scalars(stmt)]

    def pending_for_company(self, company_id: str) -> list[ContactEmail]:
        """Addresses at this company still waiting for the catch-all resolver."""
        stmt = (
            select(ContactEmailRow)
            .join(
                ContactRow,
                (ContactRow.id == ContactEmailRow.contact_id)
                & (ContactRow.workspace_id == ContactEmailRow.workspace_id),
            )
            .where(
                ContactEmailRow.workspace_id == self._workspace_id,
                ContactRow.company_id == company_id,
                ContactEmailRow.status == EmailStatus.CATCH_ALL_PENDING,
            )
            .order_by(ContactRow.rank)
        )
        return [snapshot(row, ContactEmail) for row in self._session.scalars(stmt)]

    def set_verification_skipped(
        self, email_id: str, skipped: bool, *, actor: str, reason: str | None = None
    ) -> ContactEmail:
        """The operator writes to this address whatever a verifier says (or stops doing so)."""
        row = self._row(ContactEmailRow, email_id)
        if row.verification_skipped != skipped:
            row.verification_skipped = skipped
            self._flush()
            detail: dict[str, Any] = {"status": row.status.value}
            if reason:
                detail["reason"] = reason
            kind = "email_verification_skipped" if skipped else "email_verification_restored"
            self._events.append(EntityType.CONTACT_EMAIL, row.id, kind, actor, detail)
        return snapshot(row, ContactEmail)

    def set_primary(self, email_id: str) -> ContactEmail:
        """Make one address the contact's only primary one."""
        row = self._row(ContactEmailRow, email_id)
        self._clear_primary(row.contact_id, keep=row.id)
        row.is_primary = True
        self._flush()
        return snapshot(row, ContactEmail)

    def transition(
        self,
        email_id: str,
        to: EmailStatus,
        *,
        actor: str = SYSTEM,
        verified_by: str | None = None,
        resolution_ref: str | None = None,
        verified_at: datetime | None = None,
    ) -> ContactEmail:
        row = self._row(ContactEmailRow, email_id)
        EMAIL.check(row.status, to)
        previous = row.status
        row.status = to
        if verified_by is not None:
            row.verified_by = verified_by
            row.verified_at = verified_at or utcnow()
        if resolution_ref is not None:
            row.resolution_ref = resolution_ref
        self._flush()
        self._events.append(
            EntityType.CONTACT_EMAIL,
            row.id,
            "status_changed",
            actor,
            {"from": previous.value, "to": to.value, "verified_by": verified_by},
        )
        return snapshot(row, ContactEmail)

    def _clear_primary(self, contact_id: str, keep: str | None = None) -> None:
        # Flushed straight away so the one-primary unique index never sees two at once.
        stmt = update(ContactEmailRow).where(
            ContactEmailRow.workspace_id == self._workspace_id,
            ContactEmailRow.contact_id == contact_id,
            ContactEmailRow.is_primary.is_(True),
        )
        if keep is not None:
            stmt = stmt.where(ContactEmailRow.id != keep)
        self._session.execute(stmt.values(is_primary=False))


class NoteRepository(ScopedRepository):
    """Append-only: a later note never replaces an earlier one."""

    def add(
        self,
        company_id: str,
        body: str,
        source: NoteSource,
        *,
        author: str | None = None,
        contact_id: str | None = None,
    ) -> Note:
        row = NoteRow(
            workspace_id=self._workspace_id,
            company_id=company_id,
            contact_id=contact_id,
            body=body,
            source=source,
            author=author,
        )
        self._session.add(row)
        self._session.flush()
        return snapshot(row, Note)

    def for_company(self, company_id: str) -> list[Note]:
        stmt = (
            select(NoteRow)
            .where(NoteRow.workspace_id == self._workspace_id, NoteRow.company_id == company_id)
            .order_by(NoteRow.created_at, NoteRow.id)
        )
        return [snapshot(row, Note) for row in self._session.scalars(stmt)]


class ConsentRepository(ScopedRepository):
    def add(self, contact_id: str, basis: ConsentBasis, evidence: str, recorded_by: str) -> Consent:
        """Record a consent. The same active basis twice for one person is kept once."""
        for existing in self.for_contact(contact_id):
            if existing.active and existing.basis == basis:
                return existing
        row = ConsentRow(
            workspace_id=self._workspace_id,
            contact_id=contact_id,
            basis=basis,
            evidence=evidence,
            recorded_by=recorded_by,
        )
        self._session.add(row)
        self._session.flush()
        self._events.append(
            EntityType.CONTACT,
            contact_id,
            "consent_recorded",
            recorded_by,
            {"basis": basis.value},
        )
        return snapshot(row, Consent)

    def withdraw(self, consent_id: str, actor: str) -> Consent:
        row = self._row(ConsentRow, consent_id)
        if row.withdrawn_at is None:
            row.withdrawn_at = utcnow()
            self._flush()
            self._events.append(EntityType.CONTACT, row.contact_id, "consent_withdrawn", actor, {})
        return snapshot(row, Consent)

    def for_contact(self, contact_id: str) -> list[Consent]:
        stmt = select(ConsentRow).where(
            ConsentRow.workspace_id == self._workspace_id, ConsentRow.contact_id == contact_id
        )
        return [snapshot(row, Consent) for row in self._session.scalars(stmt)]

    def has_active(self, contact_id: str) -> bool:
        return any(consent.active for consent in self.for_contact(contact_id))
