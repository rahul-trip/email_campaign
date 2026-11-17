"""LinkedIn messages: what to paste into LinkedIn for a person, and whether it was sent."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from outbound.db.models import CompanyRow, ContactRow, LinkedInMessageRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.db.types import utcnow
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import LinkedInMessage
from outbound.domain.enums import EntityType, LinkedInState
from outbound.domain.state_machines import LINKEDIN


@dataclass(frozen=True)
class LinkedInListing:
    """One row of the LinkedIn page: the text with who it is for."""

    message: LinkedInMessage
    company_name: str | None
    domain: str
    person: str | None
    title: str | None
    profile: str | None


class LinkedInRepository(ScopedRepository):
    def create(
        self,
        *,
        company_id: str,
        contact_id: str,
        note: str,
        message: str,
        issues: list[str],
        actor: str = SYSTEM,
    ) -> LinkedInMessage:
        row = LinkedInMessageRow(
            workspace_id=self._workspace_id,
            company_id=company_id,
            contact_id=contact_id,
            note=note,
            message=message,
            state=LinkedInState.DRAFTED,
            issues=issues,
        )
        self._session.add(row)
        self._session.flush()
        self._events.append(
            EntityType.LINKEDIN_MESSAGE, row.id, "created", actor, {"contact_id": contact_id}
        )
        return snapshot(row, LinkedInMessage)

    def get(self, linkedin_id: str) -> LinkedInMessage:
        return snapshot(self._row(LinkedInMessageRow, linkedin_id), LinkedInMessage)

    def for_contact(self, contact_id: str) -> LinkedInMessage | None:
        stmt = select(LinkedInMessageRow).where(
            LinkedInMessageRow.workspace_id == self._workspace_id,
            LinkedInMessageRow.contact_id == contact_id,
        )
        row = self._session.scalars(stmt).first()
        return snapshot(row, LinkedInMessage) if row else None

    def for_company(self, company_id: str) -> list[LinkedInMessage]:
        stmt = (
            select(LinkedInMessageRow)
            .where(
                LinkedInMessageRow.workspace_id == self._workspace_id,
                LinkedInMessageRow.company_id == company_id,
            )
            .order_by(LinkedInMessageRow.created_at, LinkedInMessageRow.id)
        )
        return [snapshot(row, LinkedInMessage) for row in self._session.scalars(stmt)]

    def rewrite(
        self, linkedin_id: str, *, note: str, message: str, issues: list[str], actor: str
    ) -> LinkedInMessage:
        """A fresh draft replaces the text; a message already sent is never rewritten."""
        row = self._row(LinkedInMessageRow, linkedin_id)
        if row.state is LinkedInState.SENT:
            raise ValueError("a message that was sent cannot be rewritten")
        row.note, row.message, row.issues, row.edited = note, message, issues, False
        row.state = LinkedInState.DRAFTED
        self._flush()
        self._events.append(EntityType.LINKEDIN_MESSAGE, row.id, "rewritten", actor, {})
        return snapshot(row, LinkedInMessage)

    def edit(self, linkedin_id: str, *, note: str, message: str, actor: str) -> LinkedInMessage:
        """The operator's own words. Kept as theirs: the lint issues no longer apply."""
        row = self._row(LinkedInMessageRow, linkedin_id)
        row.note, row.message, row.issues, row.edited = note, message, [], True
        self._flush()
        self._events.append(EntityType.LINKEDIN_MESSAGE, row.id, "edited", actor, {})
        return snapshot(row, LinkedInMessage)

    def transition(self, linkedin_id: str, to: LinkedInState, *, actor: str) -> LinkedInMessage:
        row = self._row(LinkedInMessageRow, linkedin_id)
        LINKEDIN.check(row.state, to)
        previous = row.state
        row.state = to
        if to is LinkedInState.SENT:
            row.sent_at, row.sent_by = utcnow(), actor
        self._flush()
        self._events.append(
            EntityType.LINKEDIN_MESSAGE,
            row.id,
            "status_changed",
            actor,
            {"from": previous.value, "to": to.value},
        )
        return snapshot(row, LinkedInMessage)

    def page(
        self, state: LinkedInState, *, limit: int, offset: int
    ) -> tuple[list[LinkedInListing], int]:
        where = (
            LinkedInMessageRow.workspace_id == self._workspace_id,
            LinkedInMessageRow.state == state,
        )
        total = int(
            self._session.scalar(select(func.count()).select_from(LinkedInMessageRow).where(*where))
            or 0
        )
        stmt = (
            select(LinkedInMessageRow, CompanyRow, ContactRow)
            .join(CompanyRow, CompanyRow.id == LinkedInMessageRow.company_id)
            .join(ContactRow, ContactRow.id == LinkedInMessageRow.contact_id)
            .where(*where, CompanyRow.workspace_id == self._workspace_id)
            .order_by(LinkedInMessageRow.created_at.desc(), LinkedInMessageRow.id)
            .limit(limit)
            .offset(offset)
        )
        rows = [
            LinkedInListing(
                snapshot(message, LinkedInMessage),
                company.name,
                company.domain,
                contact.full_name,
                contact.title,
                contact.linkedin_url,
            )
            for message, company, contact in self._session.execute(stmt)
        ]
        return rows, total
