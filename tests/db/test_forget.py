"""Forgetting a person leaves no trace of them, and leaves everyone else alone."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, String, cast, func, select

from outbound.db.base import Base
from outbound.db.models import InboundMessageRow, MailboxRow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.enums import (
    CallOutcome,
    CompanySource,
    CompanyStatus,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EntityType,
    ImportAnchor,
    ImportRowStatus,
    ImportSource,
    InboundCategory,
    MailboxGateway,
    MessageState,
    NoteSource,
    Provenance,
)
from outbound.services.forget import forget_email

PERSON = "jane@acme.com"
OTHER_ADDRESS_OF_PERSON = "jd@acme.com"
NAME = "Jane Doe"


def populate(uow: UnitOfWork, ws: str) -> dict[str, str]:
    """Jane has data in every table that can hold it. Sam, her colleague, has some too."""
    company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL, name="Acme")
    jane = uow.contacts.add(
        company.id,
        rank=1,
        source=ContactSource.SITE,
        full_name=NAME,
        first_name="Jane",
        last_name="Doe",
        title="CTO",
        linkedin_url="https://linkedin.com/in/jane-doe",
    )
    uow.contacts.update_fields(jane.id, {"title": "Chief Technology Officer"}, actor=OPERATOR)
    sam = uow.contacts.add(
        company.id,
        rank=2,
        source=ContactSource.SITE,
        full_name="Sam Roe",
        linkedin_url="https://linkedin.com/in/sam-roe",
    )
    jane_primary = uow.emails.add(jane.id, PERSON, Provenance.API_DATABASE, is_primary=True)
    uow.emails.add(jane.id, OTHER_ADDRESS_OF_PERSON, Provenance.PATTERN_INFERRED)
    sam_email = uow.emails.add(sam.id, "sam@acme.com", Provenance.API_DATABASE, is_primary=True)

    uow.notes.add(company.id, "Jane likes sailing", NoteSource.OPERATOR, contact_id=jane.id)
    uow.notes.add(company.id, "mailed jane@acme.com last week", NoteSource.OPERATOR)
    uow.notes.add(company.id, "asked about forecast error", NoteSource.OPERATOR)
    uow.consents.add(
        jane.id, ConsentBasis.VOLUNTARY_DISCLOSURE, "business card from Jane Doe", "op"
    )

    drafted = uow.messages.create(
        company_id=company.id,
        contact_id=jane.id,
        contact_email_id=jane_primary.id,
        step=0,
        subject="forecast error at acme, Jane",
        generated_body="Hi Jane Doe, writing to jane@acme.com about forecast error.",
        snippets={"hook": "Jane Doe said at Solar UK"},
        state=MessageState.APPROVED,
    )
    drafted = uow.messages.transition(
        drafted.id,
        MessageState.DRAFTED,
        expected_version=drafted.row_version,
        set_fields={"remote_draft_id": "draft-1"},
    )
    uow.messages.create(
        company_id=company.id,
        contact_id=jane.id,
        contact_email_id=jane_primary.id,
        step=1,
        subject="Re: forecast error at acme",
        generated_body="Hi Jane, following up.",
    )
    uow.messages.create(
        company_id=company.id,
        contact_id=sam.id,
        contact_email_id=sam_email.id,
        step=0,
        subject="forecast error at acme, Sam",
        generated_body="Hi Sam Roe",
    )

    uow.calls.record(
        provider="hunter",
        operation="find_email",
        request_hash="x",
        outcome=CallOutcome.HIT,
        response={"email": PERSON, "name": NAME},
        contact_id=jane.id,
        company_id=company.id,
        cost_micro_usd=24_500,
    )
    batch = uow.imports.create_batch(ImportSource.CSV, "operator", filename="expo.csv")
    uow.imports.add_row(
        batch,
        {"contact_email": "Jane@Acme.com", "contact_name": NAME, "domain": "acme.com"},
        ImportAnchor.DOMAIN,
        ImportRowStatus.MERGED,
        company_id=company.id,
    )
    uow.imports.add_row(batch, {"domain": "beta.io"}, ImportAnchor.DOMAIN, ImportRowStatus.ACCEPTED)

    mailbox = MailboxRow(
        workspace_id=ws,
        address="sales@us.example",
        gateway=MailboxGateway.IMAP,
        credentials_ref="HOSTINGER",
        sending_domain="us.example",
    )
    uow.session.add(mailbox)
    uow.session.flush()
    uow.session.add(
        InboundMessageRow(
            workspace_id=ws,
            mailbox_id=mailbox.id,
            contact_id=jane.id,
            company_id=company.id,
            rfc_message_id="<reply-1@acme.com>",
            from_address=PERSON,
            received_at=datetime(2026, 10, 17, tzinfo=UTC),
            body_excerpt="Thanks, this is Jane Doe",
            category=InboundCategory.QUESTION,
            extracted={"referred": "jane@acme.com"},
        )
    )
    uow.session.flush()
    return {"company": company.id, "jane": jane.id, "sam": sam.id, "drafted": drafted.id}


def occurrences(engine: Engine, needle: str) -> list[str]:
    """Every ``table.column`` whose text contains the needle, case-insensitively.

    Pass the owner's engine: the app role would only see one workspace, and nothing at all
    without one, which would make "no trace left" pass for the wrong reason.
    """
    found = []
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                hits = connection.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(
                        func.lower(cast(column, String)).contains(needle.lower(), autoescape=True)
                    )
                )
                if hits:
                    found.append(f"{table.name}.{column.name}")
    return found


def test_before_forgetting_the_data_really_is_everywhere(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    """Guards the scan below: if this finds little, a clean scan would prove nothing."""
    with factory(ws) as uow:
        populate(uow, ws)
        uow.commit()
    found = set(occurrences(owner_engine, PERSON))
    assert {
        "contact_emails.email",
        "messages.generated_body",
        "notes.body",
        "provider_calls.response",
        "import_rows.raw",
        "inbound_messages.from_address",
        "inbound_messages.extracted",
    } <= found
    assert {"contacts.full_name", "consents.evidence", "events.data"} & set(
        occurrences(owner_engine, NAME)
    )


def test_forgetting_removes_every_trace_of_the_person(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    with factory(ws) as uow:
        populate(uow, ws)
        uow.commit()

    with factory(ws) as uow:
        result = forget_email(uow, "  Jane@ACME.com ")
        uow.commit()

    assert result.found
    for needle in (PERSON, OTHER_ADDRESS_OF_PERSON, NAME, "jane-doe", "Chief Technology Officer"):
        assert occurrences(owner_engine, needle) == [], (
            f"{needle!r} survived in {occurrences(owner_engine, needle)}"
        )


def test_forgetting_cancels_unsent_messages_and_reports_drafts_to_delete(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        populate(uow, ws)
        uow.commit()
    with factory(ws) as uow:
        result = forget_email(uow, PERSON)
        uow.commit()
    assert result.messages_cancelled == 2
    assert result.remote_draft_ids == ("draft-1",)
    with factory(ws) as uow:
        jane = uow.contacts.for_company(uow.companies.by_domain("acme.com").id)[0]  # type: ignore[union-attr]
        states = {m.state for m in uow.messages.for_contact(jane.id)}
        assert states == {MessageState.CANCELLED}


def test_the_person_becomes_forgotten_and_suppressed_for_good(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        ids = populate(uow, ws)
        uow.commit()
    with factory(ws) as uow:
        forget_email(uow, PERSON)
        uow.commit()
    with factory(ws) as uow:
        assert uow.contacts.get(ids["jane"]).status is ContactStatus.FORGOTTEN
        assert uow.suppressions.is_email_suppressed("JANE@acme.com")
        assert uow.emails.by_address(PERSON) is None


def test_the_audit_trail_of_what_happened_survives_without_the_detail(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        ids = populate(uow, ws)
        uow.commit()
    with factory(ws) as uow:
        forget_email(uow, PERSON, actor=OPERATOR)
        uow.commit()
    with factory(ws) as uow:
        events = uow.events.for_entity(EntityType.CONTACT, ids["jane"])
        assert events[-1].type == "forgotten" and events[-1].data == {}
        assert all(e.data in ({}, {"erased": True}) for e in events)
        assert any(e.type == "status_changed" for e in events)  # still know it happened


def test_rows_and_costs_are_kept_so_the_books_still_add_up(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        ids = populate(uow, ws)
        uow.commit()
    with factory(ws) as uow:
        forget_email(uow, PERSON)
        uow.commit()
    with factory(ws) as uow:
        assert uow.calls.spend_on_company(ids["company"]) == 24_500


def test_a_colleague_and_the_company_are_left_untouched(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    with factory(ws) as uow:
        ids = populate(uow, ws)
        uow.commit()
    with factory(ws) as uow:
        forget_email(uow, PERSON)
        uow.commit()
    with factory(ws) as uow:
        sam = uow.contacts.get(ids["sam"])
        assert sam.full_name == "Sam Roe" and sam.status is ContactStatus.CANDIDATE
        assert uow.emails.by_address("sam@acme.com") is not None
        assert [m.subject for m in uow.messages.for_contact(sam.id)] == [
            "forecast error at acme, Sam"
        ]
        company = uow.companies.get(ids["company"])
        assert company.name == "Acme"
        assert company.status is CompanyStatus.NEW  # Sam can still be contacted
        assert "asked about forecast error" in [n.body for n in uow.notes.for_company(company.id)]
    assert occurrences(owner_engine, "sam@acme.com") != []


def test_a_company_with_nobody_left_to_contact_is_suppressed(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = uow.companies.create(domain="solo.io", source=CompanySource.MANUAL)
        person = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE, full_name="Pat")
        uow.emails.add(person.id, "pat@solo.io", Provenance.API_DATABASE)
        uow.commit()
        company_id = company.id
    with factory(ws) as uow:
        forget_email(uow, "pat@solo.io")
        uow.commit()
    with factory(ws) as uow:
        assert uow.companies.get(company_id).status is CompanyStatus.SUPPRESSED


def test_a_company_already_replied_is_left_as_it_was(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        company = uow.companies.create(
            domain="done.io", source=CompanySource.MANUAL, status=CompanyStatus.REPLIED
        )
        person = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE)
        uow.emails.add(person.id, "pat@done.io", Provenance.API_DATABASE)
        uow.commit()
        company_id = company.id
    with factory(ws) as uow:
        forget_email(uow, "pat@done.io")
        uow.commit()
    with factory(ws) as uow:
        assert uow.companies.get(company_id).status is CompanyStatus.REPLIED  # final: unchanged


def test_an_address_we_never_held_is_still_suppressed(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        result = forget_email(uow, "stranger@elsewhere.com")
        uow.commit()
        assert not result.found and result.messages_cancelled == 0
        assert uow.suppressions.is_email_suppressed("stranger@elsewhere.com")


def test_forgetting_twice_is_harmless(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        populate(uow, ws)
        uow.commit()
    with factory(ws) as uow:
        assert forget_email(uow, PERSON).found
        uow.commit()
    with factory(ws) as uow:
        again = forget_email(uow, PERSON)
        uow.commit()
        assert not again.found  # already erased, and still suppressed


def test_another_workspace_holding_the_same_address_is_not_touched(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(ws) as uow:
        populate(uow, ws)
        uow.commit()
    with factory(other_ws) as uow:
        company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL)
        person = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE, full_name=NAME)
        uow.emails.add(person.id, PERSON, Provenance.API_DATABASE)
        uow.commit()
        person_id = person.id
    with factory(ws) as uow:
        forget_email(uow, PERSON)
        uow.commit()
    with factory(other_ws) as uow:
        assert uow.contacts.get(person_id).full_name == NAME
        assert uow.emails.by_address(PERSON) is not None
        assert not uow.suppressions.is_email_suppressed(PERSON)


def test_a_failure_halfway_leaves_the_person_exactly_as_they_were(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    """Forget is one transaction: an error before commit undoes all of it."""
    with factory(ws) as uow:
        populate(uow, ws)
        uow.commit()
    try:
        with factory(ws) as uow:
            forget_email(uow, PERSON)
            raise RuntimeError("something went wrong before commit")
    except RuntimeError:
        pass
    assert "contact_emails.email" in occurrences(owner_engine, PERSON)
    with factory(ws) as uow:
        assert not uow.suppressions.is_email_suppressed(PERSON)
