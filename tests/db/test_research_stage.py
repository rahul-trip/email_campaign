"""The research stage under the runner: what is written, and what a sole trader leads to."""

from __future__ import annotations

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import Company
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    ContactStatus,
    HoldReason,
    LegalEntityType,
)
from outbound.providers.ports import RegistryEntry, SearchHit
from outbound.runner.guards import Guards
from outbound.runner.runner import Outcome, Runner
from outbound.stages.research.graph import ResearchDeps
from outbound.stages.research.stage import ResearchStage
from tests.stages.fakes import PAGES, FakeLlm, FakeRegistry, FakeSearch


def runner_for(
    factory: UnitOfWorkFactory,
    ws: str,
    search: FakeSearch,
    llm: FakeLlm | None = None,
    registry: FakeRegistry | None = None,
) -> Runner:
    stage = ResearchStage(ResearchDeps(search, llm or FakeLlm(), registry))
    return Runner(factory, ws, [stage], Guards())


def add(factory: UnitOfWorkFactory, ws: str, domain: str, **kwargs: object) -> str:
    with factory(ws) as uow:
        campaign = uow.campaigns.create(
            "expo",
            ["CTO"],
            icp_description="Utilities",
            research_questions=["Do they trade power?"],
        )
        company = uow.companies.create(
            domain=domain,
            source=CompanySource.MANUAL,
            campaign_id=campaign.id,
            **kwargs,  # type: ignore[arg-type]
        )
        uow.commit()
        return company.id


def test_research_saves_findings_candidates_and_moves_the_lead_on(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add(factory, ws, "acme.co.uk", name="Acme Energy")

    registry = FakeRegistry(
        [
            RegistryEntry(
                name="ACME ENERGY LIMITED", number="01234567", status="active", company_type="ltd"
            )
        ]
    )
    report = runner_for(factory, ws, FakeSearch(PAGES), registry=registry).run_pipeline()
    assert report.count("research", Outcome.ADVANCED) == 1
    with factory(ws) as uow:
        company = uow.companies.get(cid)
        assert company.status is CompanyStatus.RESEARCHED
        assert (company.country_code, company.legal_entity_type) == (
            "GB",
            LegalEntityType.CORPORATE_SUBSCRIBER,
        )
        assert (company.fit_score, company.research is not None) == (82, True)
        assert company.research_answers == {"Do they trade power?": "Yes, via a trading desk."}
        [contact] = uow.contacts.for_company(cid)
        assert (contact.full_name, contact.title, contact.source) == (
            "Jane Doe",
            "CTO",
            ContactSource.SITE,
        )


def test_a_uk_sole_trader_is_researched_but_left_with_an_unknown_entity(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add(factory, ws, "trader.co.uk", name="Bobs Boilers")
    search = FakeSearch({"https://trader.co.uk": "Bob's boiler servicing in Leeds, LS1 4AP"})
    runner_for(factory, ws, search, registry=FakeRegistry([])).run_pipeline()
    with factory(ws) as uow:
        company = uow.companies.get(cid)
        assert company.status is CompanyStatus.RESEARCHED
        assert (company.country_code, company.legal_entity_type) == ("GB", LegalEntityType.UNKNOWN)


def test_the_operators_country_is_never_replaced_by_an_inferred_one(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add(factory, ws, "acme.co.uk", country_code="IE")
    with factory(ws) as uow:
        uow.companies.update_fields(
            cid,
            {"country_code": "IE"},
            actor=OPERATOR,
            expected_version=uow.companies.get(cid).row_version,
        )
        uow.commit()
    runner_for(factory, ws, FakeSearch(PAGES)).run_pipeline()
    with factory(ws) as uow:
        assert uow.companies.get(cid).country_code == "IE"


def test_an_operator_given_contact_means_no_candidates_are_searched_for(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add(factory, ws, "acme.co.uk")
    with factory(ws) as uow:
        uow.contacts.add(cid, rank=1, source=ContactSource.OPERATOR, full_name="Sam Lee")
        uow.commit()
    llm = FakeLlm()
    runner_for(factory, ws, FakeSearch(PAGES), llm).run_pipeline()
    assert "persona" not in llm.calls
    with factory(ws) as uow:
        assert [c.full_name for c in uow.contacts.for_company(cid)] == ["Sam Lee"]


def test_a_model_failure_fails_the_lead_with_the_reason_and_keeps_the_rest(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add(factory, ws, "acme.co.uk")
    llm = FakeLlm({"site": "not json at all"})
    runner_for(factory, ws, FakeSearch(PAGES), llm).run_pipeline()
    with factory(ws) as uow:
        company = uow.companies.get(cid)
        assert (company.status, company.failed_stage) == (CompanyStatus.FAILED, "research")
        assert "no JSON" in (company.last_error or "")
        assert uow.contacts.for_company(cid) == []


def test_a_phone_number_only_suggests_a_country_so_the_lead_waits_for_the_operator(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    from outbound.stages.gate import GateStage

    cid = add(factory, ws, "acme.com", name="Acme Energy")
    search = FakeSearch(
        {"https://acme.com": "Acme builds software. London office +44 20 7946 0000."}
    )
    runner_for(factory, ws, search).run_pipeline()
    with factory(ws) as uow:
        researched = uow.companies.get(cid)
        assert researched.country_code is None
        assert (researched.research or {})["country_suggestion"]["code"] == "GB"
    Runner(factory, ws, [GateStage()], Guards()).run_pipeline()
    held = company_row(factory, ws, cid)
    assert (held.status, held.hold_reason) == (CompanyStatus.HELD, HoldReason.COUNTRY_UNKNOWN)


def company_row(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


def named_by(name: str) -> FakeLlm:
    llm = FakeLlm()
    llm.replies["site"] = {**llm.replies["site"], "company_name": name}
    return llm


def test_research_names_a_discovered_lead_after_its_own_site(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add(factory, ws, "acme.co.uk", name="6 Grid Trends to Watch in 2026")
    runner_for(factory, ws, FakeSearch(PAGES), llm=named_by("Acme Energy")).run_pipeline()
    with factory(ws) as uow:
        assert uow.companies.get(cid).name == "Acme Energy"


def test_a_name_the_operator_typed_is_kept(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = add(factory, ws, "acme.co.uk")
    with factory(ws) as uow:
        uow.companies.update_fields(
            cid,
            {"name": "Acme"},
            actor=OPERATOR,
            expected_version=uow.companies.get(cid).row_version,
        )
        uow.commit()
    runner_for(factory, ws, FakeSearch(PAGES), llm=named_by("Acme Energy Ltd")).run_pipeline()
    with factory(ws) as uow:
        assert uow.companies.get(cid).name == "Acme"


def test_a_person_a_search_could_not_place_here_is_saved_unconfirmed(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add(factory, ws, "volue.com", name="Volue")
    hits = [
        SearchHit(
            url="https://www.linkedin.com/in/someone",
            title="Sam Lee - Chief Technology Officer",
            snippet="Sam has led engineering at Volue since 2021.",
        ),
        SearchHit(url="https://www.linkedin.com/in/dan", title="Dan Roth - CTO at G&W Electric"),
    ]
    search = FakeSearch({"https://volue.com": "Volue builds software for grids."}, hits)
    runner_for(factory, ws, search).run_pipeline()
    with factory(ws) as uow:
        people = uow.contacts.for_company(cid)
    assert [(p.full_name, p.status) for p in people] == [("Sam Lee", ContactStatus.UNCONFIRMED)]


def test_dated_news_found_by_search_is_saved_with_the_research(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    from datetime import UTC, datetime, timedelta

    cid = add(factory, ws, "acme.co.uk", name="Acme Energy")
    when = (datetime.now(UTC) - timedelta(days=9)).date().isoformat()
    news = [
        SearchHit(
            url="https://news.example.com/acme-leeds",
            title="Acme Energy wins Leeds grid contract",
            snippet="Acme Energy signed a three-year deal.",
            published_date=when,
        )
    ]
    llm = FakeLlm()
    llm.replies["news"] = {
        "company": [{"n": 1, "detail": "Acme won a Leeds contract."}],
        "market": [],
    }
    runner_for(factory, ws, FakeSearch(PAGES, news=news), llm=llm).run_pipeline()
    with factory(ws) as uow:
        research = uow.companies.get(cid).research or {}
    assert research["news_items"] == [
        {
            "date": when,
            "headline": "Acme Energy wins Leeds grid contract",
            "detail": "Acme won a Leeds contract.",
            "matters": "",
            "url": "https://news.example.com/acme-leeds",
        }
    ]
    assert research["triggers"] == []
