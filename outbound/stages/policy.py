"""The country-policy decision for a company as it stands now.

Used by the gate to decide, and by the runner's guard to re-check before every later stage,
so a policy edited after a lead was qualified still applies to it.
"""

from __future__ import annotations

from outbound.db.uow import UnitOfWork
from outbound.domain.entities import Company, Contact
from outbound.domain.enums import WORKABLE_CONTACT_STATUSES, Provenance
from outbound.domain.policies import PolicyDecision, decide_country_policy


def _primary_provenance(uow: UnitOfWork, contacts: list[Contact]) -> Provenance | None:
    for contact in contacts:
        for address in uow.emails.for_contact(contact.id):
            if address.is_primary:
                return address.provenance
    return None


def policy_decision_for(
    uow: UnitOfWork,
    company: Company,
    *,
    email_provenance: Provenance | None = None,
    recipient_id: str | None = None,
) -> PolicyDecision:
    """The decision for ``company`` now.

    Before a recipient is known (the gate, the runner's guard) a consent from anyone at the
    company counts, so the lead is not held while the right person is still being found. Once
    the email, copy or deliver step names the recipient, only *their* consent counts: someone
    else's consent never allows writing to this person.
    """
    policy = uow.policies.get(company.country_code) if company.country_code else None
    contacts = [
        c for c in uow.contacts.for_company(company.id) if c.status in WORKABLE_CONTACT_STATUSES
    ]
    if recipient_id is not None:
        contacts = [c for c in contacts if c.id == recipient_id]
    consented = any(uow.consents.has_active(c.id) for c in contacts)
    if email_provenance is None:  # not told which address: use the one the company will send to
        email_provenance = _primary_provenance(uow, contacts)
    return decide_country_policy(
        country_code=company.country_code,
        legal_entity_type=company.legal_entity_type,
        policy=policy,
        email_provenance=email_provenance,
        has_active_consent=consented,
    )
