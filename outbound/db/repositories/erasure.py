"""The scrub behind "forget": blank every personal field about one person, in one place.

Rows are kept (so counts, costs and the audit trail of *what happened* survive) but every
column that could identify the person is emptied. Required text columns get a placeholder.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast, func, select, update

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

    def _scrub_provider_calls(self, contact_id: str, needles: list[str]) -> None:
        """Blank cached vendor answers about the person.

        Answers are linked to a contact only when the call was made for one. A page or a model
        reply that merely *mentions* the person (a team page, a research summary) has no such
        link, so those are found by their text.
        """
        text = func.lower(cast(ProviderCallRow.response, String))
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
        raw_text = func.lower(cast(ImportRowRow.raw, String))
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
