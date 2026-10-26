"""Forget a person: stop contacting them, and remove what identifies them.

Runs inside the caller's unit of work and does not commit, so it succeeds or fails as one.
It cannot reach the mailbox, so it returns the ids of drafts the caller must delete there
*after* committing.
"""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.uow import UnitOfWork
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import Message
from outbound.domain.enums import (
    WORKABLE_CONTACT_STATUSES,
    CompanyStatus,
    ContactStatus,
    EntityType,
    MessageState,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.hashing import normalise
from outbound.domain.state_machines import COMPANY

_UNSENT = (MessageState.GENERATED, MessageState.APPROVED, MessageState.DRAFTED)


# A draft saved in a mailbox: its Message-ID and the mailbox holding it (None: the default).
DraftRef = tuple[str, str | None]


@dataclass(frozen=True)
class ForgetResult:
    found: bool  # whether the address belonged to anyone we hold
    messages_cancelled: int
    drafts: tuple[DraftRef, ...]  # unsent drafts to delete from their mailbox after commit


def drafts_of(messages: list[Message]) -> list[DraftRef]:
    """The drafts among these messages, with the mailbox each one is in."""
    return [
        (m.remote_draft_id, m.mailbox_id)
        for m in messages
        if m.state is MessageState.DRAFTED and m.remote_draft_id
    ]


def stop_contact(uow: UnitOfWork, contact_id: str, actor: str) -> tuple[int, list[DraftRef]]:
    """Cancel every email to this person that has not been sent.

    Returns how many were cancelled and the drafts already saved in a mailbox, which the caller
    must delete there once the database change is committed.
    """
    draft_ids: list[DraftRef] = []
    cancelled = 0
    for message in uow.messages.for_contact(contact_id):
        if message.state not in _UNSENT:
            continue
        draft_ids += drafts_of([message])
        uow.messages.transition(
            message.id, MessageState.CANCELLED, expected_version=message.row_version, actor=actor
        )
        cancelled += 1
    return cancelled, draft_ids


def suppress_if_nobody_left(
    uow: UnitOfWork, company_id: str, *, leaving: str | None, actor: str, reason: str
) -> None:
    """With nobody left to write to at a company, the company stops here."""
    company = uow.companies.get(company_id)
    others = [
        c
        for c in uow.contacts.for_company(company_id)
        if c.id != leaving and c.status in WORKABLE_CONTACT_STATUSES
    ]
    if not others and COMPANY.allows(company.status, CompanyStatus.SUPPRESSED):
        uow.companies.transition(
            company_id,
            CompanyStatus.SUPPRESSED,
            expected_version=company.row_version,
            actor=actor,
            reason=reason,
        )


def forget_email(uow: UnitOfWork, email: str, *, actor: str = OPERATOR) -> ForgetResult:
    address = normalise(email)
    # Suppress first, even for an address we do not hold, so it can never be imported later.
    uow.suppressions.add(SuppressionKind.EMAIL, address, SuppressionReason.FORGET, actor=actor)
    uow.directory.remove_person(address)  # and the shared directory, for every customer

    known = uow.emails.by_address(address)
    if known is None:
        return ForgetResult(found=False, messages_cancelled=0, drafts=())

    contact = uow.contacts.get(known.contact_id)
    cancelled, draft_ids = stop_contact(uow, contact.id, actor)
    uow.contacts.transition(contact.id, ContactStatus.FORGOTTEN, actor=actor, reason="forget")
    uow.erasure.scrub_contact(contact.id, address)
    suppress_if_nobody_left(
        uow,
        contact.company_id,
        leaving=contact.id,
        actor=actor,
        reason="no contact left after a forget request",
    )
    uow.events.append(EntityType.CONTACT, contact.id, "forgotten", actor, {})
    return ForgetResult(found=True, messages_cancelled=cancelled, drafts=tuple(draft_ids))
