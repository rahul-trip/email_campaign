"""The scrub behind "forget": blank every personal field about one person, in one place.

Rows are kept (so counts, costs and the audit trail of *what happened* survive) but every
column that could identify the person is emptied. Required text columns get a placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, String, delete, func, select, update
from sqlalchemy import cast as sql_cast

from outbound.db.models import (
    CompanyRow,
    ConsentRow,
    ContactEmailRow,
    ContactRow,
    EventRow,
    ImportRowRow,
    InboundMessageRow,
    MessageRow,
    NoteRow,
    ProviderCallRow,
)
from outbound.db.repositories.base import ScopedRepository
from outbound.domain.enums import EntityType

ERASED = "[erased]"


@dataclass(frozen=True)
class DeletedLead:
    contacts: int
    emails: int
    messages: int
    events: int


MIN_NAME_LENGTH = 5  # shorter "names" would match far too much ordinary text


def redact(value: Any, needles: list[str]) -> Any:
    """``value`` (any JSON) with every case-insensitive occurrence of a needle replaced."""
    if isinstance(value, str):
        for needle in needles:
            lowered, start = value.lower(), 0
            pieces: list[str] = []
            while (hit := lowered.find(needle.lower(), start)) != -1:
                pieces.append(value[start:hit])
                start = hit + len(needle)
            pieces.append(value[start:])
            value = ERASED.join(pieces) if len(pieces) > 1 else value
        return value
    if isinstance(value, list):
        return [redact(item, needles) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, needles) for key, item in value.items()}
    return value


class ErasureRepository(ScopedRepository):
    def scrub_contact(self, contact_id: str, address: str | None) -> None:
        """Remove the personal data of one contact and, if known, their email address."""
        ws = self._workspace_id
        contact = self._row(ContactRow, contact_id)
        company_id = contact.company_id
        # What identifies this person in running text: their address and their full name.
        # Taken before the columns are blanked below.
        needles = [n for n in (address, contact.full_name) if n and len(n) >= MIN_NAME_LENGTH]
        email_ids = list(
            self._session.scalars(
                select(ContactEmailRow.id).where(
                    ContactEmailRow.workspace_id == ws, ContactEmailRow.contact_id == contact_id
                )
            )
        )
        message_ids = list(
            self._session.scalars(
                select(MessageRow.id).where(
                    MessageRow.workspace_id == ws, MessageRow.contact_id == contact_id
                )
            )
        )

        for name in ("full_name", "first_name", "last_name", "title", "seniority", "linkedin_url"):
            setattr(contact, name, None)
        contact.manual_fields = []

        self._session.execute(
            update(ContactEmailRow)
            .where(ContactEmailRow.workspace_id == ws, ContactEmailRow.contact_id == contact_id)
            .values(email=None, found_by=None, verified_by=None, resolution_ref=None)
        )
        self._session.execute(
            update(MessageRow)
            .where(MessageRow.workspace_id == ws, MessageRow.contact_id == contact_id)
            .values(subject=ERASED, generated_body=ERASED, final_body=None, snippets=None)
        )
        self._session.execute(
            update(InboundMessageRow)
            .where(InboundMessageRow.workspace_id == ws, InboundMessageRow.contact_id == contact_id)
            .values(from_address=None, body_excerpt=None, extracted=None)
        )
        self._session.execute(
            update(ConsentRow)
            .where(ConsentRow.workspace_id == ws, ConsentRow.contact_id == contact_id)
            .values(evidence=ERASED)
        )
        self._scrub_provider_calls(contact_id, needles)
        self._scrub_company(company_id, needles)
        self._scrub_notes(contact_id, address)
        self._scrub_import_rows(address)
        self._scrub_events(contact_id, email_ids, message_ids)
        self._session.flush()

    def delete_company(self, company_id: str, *, actor: str, note: dict[str, Any]) -> DeletedLead:
        """Remove a lead and everything that hangs off it, in dependency order.

        The cost ledger keeps its rows (spend is real) but loses the link to the lead and the
        stored vendor answers. The operator's import row keeps its place but loses its text,
        which can hold names and addresses. Every event about the lead and its people is deleted
        except one, written here, that says it happened.
        """
        ws = self._workspace_id
        company = self._row(CompanyRow, company_id)
        contact_ids = list(
            self._session.scalars(
                select(ContactRow.id).where(
                    ContactRow.workspace_id == ws, ContactRow.company_id == company_id
                )
            )
        )
        email_ids = list(
            self._session.scalars(
                select(ContactEmailRow.id).where(
                    ContactEmailRow.workspace_id == ws,
                    ContactEmailRow.contact_id.in_(contact_ids),
                )
            )
        )
        message_ids = list(
            self._session.scalars(
                select(MessageRow.id).where(
                    MessageRow.workspace_id == ws, MessageRow.company_id == company_id
                )
            )
        )

        def run(statement: Any) -> int:
            return int(cast(CursorResult[Any], self._session.execute(statement)).rowcount or 0)

        run(
            delete(InboundMessageRow).where(
                InboundMessageRow.workspace_id == ws,
                (InboundMessageRow.company_id == company_id)
                | InboundMessageRow.contact_id.in_(contact_ids)
                | InboundMessageRow.message_id.in_(message_ids),
            )
        )
        run(
            update(ProviderCallRow)
            .where(
                ProviderCallRow.workspace_id == ws,
                (ProviderCallRow.company_id == company_id)
                | ProviderCallRow.contact_id.in_(contact_ids),
            )
            .values(company_id=None, contact_id=None, response=None)
        )
        run(
            update(ImportRowRow)
            .where(ImportRowRow.workspace_id == ws, ImportRowRow.company_id == company_id)
            .values(company_id=None, raw={"erased": True})
        )
        messages = run(
            delete(MessageRow).where(MessageRow.workspace_id == ws, MessageRow.id.in_(message_ids))
        )
        run(
            delete(ConsentRow).where(
                ConsentRow.workspace_id == ws, ConsentRow.contact_id.in_(contact_ids)
            )
        )
        emails = run(
            delete(ContactEmailRow).where(
                ContactEmailRow.workspace_id == ws, ContactEmailRow.id.in_(email_ids)
            )
        )
        run(delete(NoteRow).where(NoteRow.workspace_id == ws, NoteRow.company_id == company_id))
        contacts = run(
            delete(ContactRow).where(ContactRow.workspace_id == ws, ContactRow.id.in_(contact_ids))
        )
        events = 0
        for entity_type, ids in (
            (EntityType.COMPANY, [company_id]),
            (EntityType.CONTACT, contact_ids),
            (EntityType.CONTACT_EMAIL, email_ids),
            (EntityType.MESSAGE, message_ids),
        ):
            if ids:
                events += run(
                    delete(EventRow).where(
                        EventRow.workspace_id == ws,
                        EventRow.entity_type == entity_type,
                        EventRow.entity_id.in_(ids),
                    )
                )
        self._session.delete(company)
        self._session.flush()
        # The one thing left behind: that it happened, when, by whom, and how much went with it.
        self._events.append(EntityType.COMPANY, company_id, "lead_deleted", actor, note)
        self._session.flush()
        return DeletedLead(contacts, emails, messages, events)

    def delete_contact(self, contact_id: str, *, actor: str) -> None:
        """Remove one person who was never written to, such as someone matched by mistake.

        The caller checks that no message names them. Cached vendor answers keep their cost
        but lose the link, and the person's own events go with them; the company keeps one
        ``person_removed`` event that says it happened.
        """
        ws = self._workspace_id
        contact = self._row(ContactRow, contact_id)
        email_ids = list(
            self._session.scalars(
                select(ContactEmailRow.id).where(
                    ContactEmailRow.workspace_id == ws, ContactEmailRow.contact_id == contact_id
                )
            )
        )
        self._session.execute(
            update(ProviderCallRow)
            .where(ProviderCallRow.workspace_id == ws, ProviderCallRow.contact_id == contact_id)
            .values(contact_id=None, response=None)
        )
        self._session.execute(
            update(InboundMessageRow)
            .where(InboundMessageRow.workspace_id == ws, InboundMessageRow.contact_id == contact_id)
            .values(contact_id=None)
        )
        self._session.execute(
            update(NoteRow)
            .where(NoteRow.workspace_id == ws, NoteRow.contact_id == contact_id)
            .values(contact_id=None)
        )
        self._session.execute(
            delete(ConsentRow).where(
                ConsentRow.workspace_id == ws, ConsentRow.contact_id == contact_id
            )
        )
        self._session.execute(
            delete(ContactEmailRow).where(
                ContactEmailRow.workspace_id == ws, ContactEmailRow.id.in_(email_ids)
            )
        )
        for entity_type, ids in (
            (EntityType.CONTACT, [contact_id]),
            (EntityType.CONTACT_EMAIL, email_ids),
        ):
            if ids:
                self._session.execute(
                    delete(EventRow).where(
                        EventRow.workspace_id == ws,
                        EventRow.entity_type == entity_type,
                        EventRow.entity_id.in_(ids),
                    )
                )
        company_id = contact.company_id
        self._session.delete(contact)
        self._session.flush()
        self._events.append(
            EntityType.COMPANY, company_id, "person_removed", actor, {"contact_id": contact_id}
        )
        self._session.flush()

    def _scrub_provider_calls(self, contact_id: str, needles: list[str]) -> None:
        """Blank cached vendor answers about the person.

        Answers are linked to a contact only when the call was made for one. A page or a model
        reply that merely *mentions* the person (a team page, a research summary) has no such
        link, so those are found by their text.
        """
        text = func.lower(sql_cast(ProviderCallRow.response, String))
        matches: Any = ProviderCallRow.contact_id == contact_id
        for needle in needles:
            matches = matches | text.contains(needle.lower(), autoescape=True)
        self._session.execute(
            update(ProviderCallRow)
            .where(ProviderCallRow.workspace_id == self._workspace_id, matches)
            .values(response=None)
        )

    def _scrub_company(self, company_id: str, needles: list[str]) -> None:
        """Remove the person from the company's research, and from its event history."""
        if not needles:
            return
        row = self._row(CompanyRow, company_id)
        row.research = redact(row.research, needles)
        row.research_answers = redact(row.research_answers, needles)
        row.fit_reason = redact(row.fit_reason, needles)
        events = self._session.scalars(
            select(EventRow).where(
                EventRow.workspace_id == self._workspace_id,
                EventRow.entity_type == EntityType.COMPANY,
                EventRow.entity_id == company_id,
            )
        )
        for event in events:
            event.data = redact(event.data, needles)

    def _scrub_notes(self, contact_id: str, address: str | None) -> None:
        condition: Any = NoteRow.contact_id == contact_id
        if address:
            condition = condition | func.lower(NoteRow.body).contains(address, autoescape=True)
        self._session.execute(
            update(NoteRow)
            .where(NoteRow.workspace_id == self._workspace_id, condition)
            .values(body=ERASED)
        )

    def _scrub_import_rows(self, address: str | None) -> None:
        if not address:
            return
        raw_text = func.lower(sql_cast(ImportRowRow.raw, String))
        self._session.execute(
            update(ImportRowRow)
            .where(
                ImportRowRow.workspace_id == self._workspace_id,
                raw_text.contains(address, autoescape=True),
            )
            .values(raw={"erased": True})
        )

    def _scrub_events(self, contact_id: str, email_ids: list[str], message_ids: list[str]) -> None:
        for entity_type, ids in (
            (EntityType.CONTACT, [contact_id]),
            (EntityType.CONTACT_EMAIL, email_ids),
            (EntityType.MESSAGE, message_ids),
        ):
            if not ids:
                continue
            self._session.execute(
                update(EventRow)
                .where(
                    EventRow.workspace_id == self._workspace_id,
                    EventRow.entity_type == entity_type,
                    EventRow.entity_id.in_(ids),
                )
                .values(data={"erased": True})
            )
