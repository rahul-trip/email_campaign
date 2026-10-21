"""The one-off clean-up of the first discovery run: what it plans, what it does, and that a
second run finds nothing left."""

from __future__ import annotations

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    EmailStatus,
    MessageState,
    Provenance,
)
from scripts.fix_discovery_data import plan

C = CompanyStatus


def seed(factory: UnitOfWorkFactory, ws: str) -> None:
    """The shape of the live data on 2026-10-19."""
    with factory(ws) as uow:
        amperon = uow.companies.create(
            domain="amperon.co",
            source=CompanySource.DISCOVERY,
            name="6 Grid Trends to Watch in 2026",
        )
        version = amperon.row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.FAILED):
            extra = {"failed_stage": "email", "last_error": "x"} if step is C.FAILED else {}
            version = uow.companies.transition(
                amperon.id,
                step,
                expected_version=version,
                **extra,  # type: ignore[arg-type]
            ).row_version
        for name in ("Del Misenheimer", "Dan Roth"):
            uow.contacts.add(amperon.id, rank=1, source=ContactSource.SEARCH, full_name=name)
        uow.companies.create(domain="tata.com", source=CompanySource.MANUAL, name="tata power")
        rebase = uow.companies.create(domain="rebase.energy", source=CompanySource.MANUAL)
        version = rebase.row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.EMAIL_READY, C.COPY_READY):
            version = uow.companies.transition(
                rebase.id, step, expected_version=version
            ).row_version
        cto = uow.contacts.add(
            rebase.id, rank=1, source=ContactSource.SITE, full_name="Mihai Chiru"
        )
        uow.contacts.add(
            rebase.id, rank=2, source=ContactSource.SITE, full_name="Sebastian Haglund"
        )
        address = uow.emails.add(
            cto.id, "mihai@rebase.energy", Provenance.API_DATABASE, status=EmailStatus.VALID
        )
        uow.messages.create(
            company_id=rebase.id,
            contact_id=cto.id,
            contact_email_id=address.id,
            step=0,
            subject="s",
            generated_body="b",
        )
        uow.commit()


def test_the_clean_up_shows_its_plan_does_it_and_then_has_nothing_left(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed(factory, ws)
    actions = plan(factory, ws, rerun_research=True)
    assert [a.what.split(":")[0] for a in actions] == [
        "amperon.co",
        "amperon.co",
        "amperon.co",
        "add tatapower.com as 'Tata Power' (country None), then delete the tata.com lead (new)",
        "rebase.energy",
        "amperon.co",
    ]
    with factory(ws) as uow:  # planning changed nothing
        assert uow.companies.by_domain("amperon.co").name == "6 Grid Trends to Watch in 2026"  # type: ignore[union-attr]

    for action in actions:
        action.do()

    with factory(ws) as uow:
        amperon = uow.companies.by_domain("amperon.co")
        assert amperon is not None
        assert (amperon.name, amperon.status, amperon.manual_fields) == ("Amperon", C.NEW, ())
        assert uow.contacts.for_company(amperon.id) == []
        assert uow.companies.by_domain("tata.com") is None
        tata = uow.companies.by_domain("tatapower.com")
        assert tata is not None and tata.name == "Tata Power"
        rebase = uow.companies.by_domain("rebase.energy")
        assert rebase is not None and rebase.status is C.CONTACTS_FOUND
        assert uow.contacts.for_company(rebase.id)[0].full_name == "Sebastian Haglund"
        assert [m.state for m in uow.messages.for_company(rebase.id)] == [MessageState.CANCELLED]
    assert plan(factory, ws, rerun_research=True) == []
