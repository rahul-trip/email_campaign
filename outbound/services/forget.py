"""Forget a person: stop contacting them, and remove what identifies them.

Runs inside the caller's unit of work and does not commit, so it succeeds or fails as one.
It cannot reach the mailbox, so it returns the ids of drafts the caller must delete there
*after* committing.
"""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.uow import UnitOfWork
from outbound.domain.actors import OPERATOR
from outbound.domain.enums import (
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
_STILL_WORKABLE = (ContactStatus.CANDIDATE, ContactStatus.ACTIVE)


@dataclass(frozen=True)
class ForgetResult:
    found: bool  # whether the address belonged to anyone we hold
    messages_cancelled: int
    remote_draft_ids: tuple[str, ...]  # unsent drafts to delete from the mailbox after commit


def forget_email(uow: UnitOfWork, email: str, *, actor: str = OPERATOR) -> ForgetResult:
    address = normalise(email)
    # Suppress first, even for an address we do not hold, so it can never be imported later.
    uow.suppressions.add(SuppressionKind.EMAIL, address, SuppressionReason.FORGET, actor=actor)

    known = uow.emails.by_address(address)
    if known is None:
        return ForgetResult(found=False, messages_cancelled=0, remote_draft_ids=())

    contact = uow.contacts.get(known.contact_id)
    draft_ids: list[str] = []
    cancelled = 0
    for message in uow.messages.for_contact(contact.id):
        if message.state not in _UNSENT:
            continue
        if message.state is MessageState.DRAFTED and message.remote_draft_id:
            draft_ids.append(message.remote_draft_id)
        uow.messages.transition(
            message.id, MessageState.CANCELLED, expected_version=message.row_version, actor=actor
        )
        cancelled += 1

    uow.contacts.transition(contact.id, ContactStatus.FORGOTTEN, actor=actor, reason="forget")
    uow.erasure.scrub_contact(contact.id, address)

    # With nobody left to write to, the company stops here.
    company = uow.companies.get(contact.company_id)
    others = [
        c
        for c in uow.contacts.for_company(company.id)
        if c.id != contact.id and c.status in _STILL_WORKABLE
    ]
    if not others and COMPANY.allows(company.status, CompanyStatus.SUPPRESSED):
        uow.companies.transition(
            company.id,
            CompanyStatus.SUPPRESSED,
            expected_version=company.row_version,
            actor=actor,
            reason="no contact left after a forget request",
        )

    uow.events.append(EntityType.CONTACT, contact.id, "forgotten", actor, {})
    return ForgetResult(found=True, messages_cancelled=cancelled, remote_draft_ids=tuple(draft_ids))
