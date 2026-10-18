"""The scrub behind "forget": blank every personal field about one person, in one place.

Rows are kept (so counts, costs and the audit trail of *what happened* survive) but every
column that could identify the person is emptied. Required text columns get a placeholder.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast, func, select, update

from outbound.db.models import (
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


class ErasureRepository(ScopedRepository):
    def scrub_contact(self, contact_id: str, address: str | None) -> None:
        """Remove the personal data of one contact and, if known, their email address."""
        ws = self._workspace_id
        contact = self._row(ContactRow, contact_id)
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
        self._session.execute(
            update(ProviderCallRow)
            .where(ProviderCallRow.workspace_id == ws, ProviderCallRow.contact_id == contact_id)
            .values(response=None)
        )
        self._scrub_notes(contact_id, address)
        self._scrub_import_rows(address)
        self._scrub_events(contact_id, email_ids, message_ids)
        self._session.flush()

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
