"""The database itself refuses bad data, whatever the application does.

These tests go around the repositories on purpose: the repositories are polite (they clear a
contact's old primary address before adding a new one, for instance), so only a direct insert
shows that the constraint is really there.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from outbound.db.models import (
    ContactEmailRow,
    ContactRow,
    CountryPolicyRow,
    SuppressionRow,
)
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.enums import (
    CompanySource,
    ContactSource,
    ImportSource,
    MessageState,
    PolicyRule,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)


def seeded(uow: UnitOfWork) -> tuple[str, str]:
    """A company and a contact; returns their ids."""
    company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL)
    contact = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE)
    uow.session.flush()
    return company.id, contact.id


def raw_update(session: Session, sql: str, **params: object) -> None:
    session.execute(text(sql), params)
    session.flush()


# ------------------------------------------------------------------ uniqueness (SCHEMA section 3)


def test_two_primary_addresses_for_one_contact_are_refused(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        _, contact_id = seeded(uow)
        for address in ("a@acme.com", "b@acme.com"):
            uow.session.add(
                ContactEmailRow(
                    workspace_id=ws,
                    contact_id=contact_id,
                    email=address,
                    provenance=Provenance.API_DATABASE,
                    is_primary=True,
                )
            )
        with pytest.raises(IntegrityError):
            uow.session.flush()


def test_many_non_primary_addresses_are_fine(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        _, contact_id = seeded(uow)
        for address in ("a@acme.com", "b@acme.com", "c@acme.com"):
            uow.session.add(
                ContactEmailRow(
                    workspace_id=ws,
                    contact_id=contact_id,
                    email=address,
                    provenance=Provenance.API_DATABASE,
                    is_primary=False,
                )
            )
        uow.session.flush()


def test_erased_addresses_do_not_collide_on_the_unique_email(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    """After a forget request the address is NULL, and any number of rows may be NULL."""
    with factory(ws) as uow:
        _, contact_id = seeded(uow)
        for _ in range(3):
            uow.session.add(
                ContactEmailRow(
                    workspace_id=ws,
                    contact_id=contact_id,
                    email=None,
                    provenance=Provenance.API_DATABASE,
                )
            )
        uow.session.flush()


def test_a_duplicate_suppression_is_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        for _ in range(2):
            uow.session.add(
                SuppressionRow(
                    workspace_id=ws,
                    kind=SuppressionKind.EMAIL,
                    value_hash="a" * 64,
                    reason=SuppressionReason.OPT_OUT,
                )
            )
        with pytest.raises(IntegrityError):
            uow.session.flush()


def test_the_same_hash_may_be_suppressed_as_an_email_and_as_a_domain(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        for kind in (SuppressionKind.EMAIL, SuppressionKind.DOMAIN):
            uow.session.add(
                SuppressionRow(
                    workspace_id=ws, kind=kind, value_hash="b" * 64, reason=SuppressionReason.MANUAL
                )
            )
        uow.session.flush()


def test_one_policy_per_country_per_workspace(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        for _ in range(2):
            uow.session.add(
                CountryPolicyRow(workspace_id=ws, country_code="GB", rule=PolicyRule.BLOCK)
            )
        with pytest.raises(IntegrityError):
            uow.session.flush()


def test_a_second_contact_may_not_claim_a_linkedin_profile_in_another_company(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        first = uow.companies.create(domain="a.com", source=CompanySource.MANUAL)
        second = uow.companies.create(domain="b.com", source=CompanySource.MANUAL)
        for company_id in (first.id, second.id):
            uow.session.add(
                ContactRow(
                    workspace_id=ws,
                    company_id=company_id,
                    rank=1,
                    source=ContactSource.SITE,
                    linkedin_url="https://linkedin.com/in/jane",
                )
            )
        with pytest.raises(IntegrityError):
            uow.session.flush()


# ------------------------------------------------------------------ value ranges and enums


@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'bogus'",
        "hold_reason = 'bogus'",
        "legal_entity_type = 'bogus'",
        "source = 'bogus'",
        "fit_score = 101",
        "fit_score = -1",
        "country_code = 'GBR'",
        "country_code = 'G'",
    ],
)
def test_the_database_refuses_bad_company_values(
    factory: UnitOfWorkFactory, ws: str, assignment: str
) -> None:
    with factory(ws) as uow:
        company_id, _ = seeded(uow)
        # An over-long country code is a data error on Postgres and a failed CHECK on SQLite.
        with pytest.raises((IntegrityError, DataError)):
            raw_update(
                uow.session, f"UPDATE companies SET {assignment} WHERE id = :id", id=company_id
            )


def test_a_company_with_no_hold_reason_is_allowed(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        company_id, _ = seeded(uow)
        raw_update(
            uow.session, "UPDATE companies SET hold_reason = NULL WHERE id = :id", id=company_id
        )


@pytest.mark.parametrize("score", [-1, 101])
def test_a_campaign_fit_minimum_must_be_between_0_and_100(
    factory: UnitOfWorkFactory, ws: str, score: int
) -> None:
    with factory(ws) as uow:
        uow.campaigns.create("expo", ["CTO"])
        uow.session.flush()
        with pytest.raises(IntegrityError):
            raw_update(uow.session, "UPDATE campaigns SET min_fit_score = :s", s=score)


def test_a_country_policy_code_must_be_two_letters(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.session.add(CountryPolicyRow(workspace_id=ws, country_code="GB", rule=PolicyRule.ALLOW))
        uow.session.flush()
        with pytest.raises((IntegrityError, DataError)):
            raw_update(uow.session, "UPDATE country_policies SET country_code = 'GBR'")


# ------------------------------------------------------------------ foreign keys


def test_foreign_keys_are_enforced(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.session.add(
            ContactRow(
                workspace_id=ws, company_id="does-not-exist", rank=1, source=ContactSource.SITE
            )
        )
        with pytest.raises(IntegrityError):
            uow.session.flush()


def test_a_row_cannot_point_at_a_missing_workspace(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.session.add(
            CountryPolicyRow(
                workspace_id="no-such-workspace", country_code="GB", rule=PolicyRule.ALLOW
            )
        )
        with pytest.raises(IntegrityError):
            uow.session.flush()


def test_deleting_a_company_removes_its_contacts_and_their_addresses(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company_id, contact_id = seeded(uow)
        uow.emails.add(contact_id, "jane@acme.com", Provenance.API_DATABASE)
        uow.session.flush()
        raw_update(uow.session, "DELETE FROM companies WHERE id = :id", id=company_id)
        for table in ("contacts", "contact_emails"):
            assert uow.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == 0


# ------------------------------------------------------------------ migration 0002


def _message_for(uow: UnitOfWork, company_id: str, contact_id: str, state: MessageState) -> None:
    address = uow.emails.add(
        contact_id, f"{company_id[:6]}{state.value}@acme.com", Provenance.API_DATABASE
    )
    uow.messages.create(
        company_id=company_id,
        contact_id=contact_id,
        contact_email_id=address.id,
        step=0,
        subject="s",
        generated_body="b",
        state=state,
    )


def test_a_cancelled_or_rejected_message_does_not_block_a_new_first_email(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company_id, contact_id = seeded(uow)
        _message_for(uow, company_id, contact_id, MessageState.CANCELLED)
        _message_for(uow, company_id, contact_id, MessageState.REJECTED)
        _message_for(uow, company_id, contact_id, MessageState.GENERATED)  # the live one
        uow.session.flush()


@pytest.mark.parametrize(
    "first", [MessageState.GENERATED, MessageState.APPROVED, MessageState.SENT]
)
def test_two_live_messages_for_one_touch_are_still_refused(
    factory: UnitOfWorkFactory, ws: str, first: MessageState
) -> None:
    with factory(ws) as uow:
        company_id, contact_id = seeded(uow)
        _message_for(uow, company_id, contact_id, first)
        uow.session.flush()
        with pytest.raises(IntegrityError):
            _message_for(uow, company_id, contact_id, MessageState.GENERATED)


def test_one_batch_per_webhook_event_even_if_two_arrive_together(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        uow.imports.create_batch(ImportSource.WEBHOOK, "webhook", filename="webhook:evt-1")
        uow.session.flush()
        with pytest.raises(IntegrityError):
            uow.imports.create_batch(ImportSource.WEBHOOK, "webhook", filename="webhook:evt-1")


def test_file_imports_with_the_same_name_are_still_allowed(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        for _ in range(2):
            uow.imports.create_batch(ImportSource.CSV, "operator", filename="targets.csv")
        uow.session.flush()


def test_workspace_names_are_unique(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory.admin() as admin, pytest.raises(IntegrityError):
        admin.workspaces.create("acme", {}, {})  # the fixture already made one called "acme"
