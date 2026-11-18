"""The read-only endpoints the new web app (web3) needs: lead filters and summaries, per-day
counts, fit bands and the discovery plan. None of them writes anything."""

from __future__ import annotations

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import AUTO
from outbound.domain.enums import (
    CallOutcome,
    CompanySource,
    ContactSource,
    ContactStatus,
    EmailStatus,
    EntityType,
    Provenance,
)
from tests.api.conftest import Api


def _lead(
    factory: UnitOfWorkFactory,
    ws: str,
    domain: str,
    *,
    fit: int | None = None,
    source: CompanySource = CompanySource.MANUAL,
    country: str | None = None,
    name: str | None = None,
) -> str:
    with factory(ws) as uow:
        company = uow.companies.create(
            domain=domain, source=source, country_code=country, name=name
        )
        if fit is not None:
            uow.companies.update_fields(
                company.id, {"fit_score": fit}, actor="test", expected_version=company.row_version
            )
        uow.commit()
        return company.id


def test_leads_filter_by_fit_hot_source_and_country_and_sort_by_fit(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    _lead(factory, ws, "hot.io", fit=91, source=CompanySource.DISCOVERY, country="GB")
    _lead(factory, ws, "warm.io", fit=70, country="IE")
    _lead(factory, ws, "edge.io", fit=80, country="GB")  # 80 is not hot: hot is above 80
    _lead(factory, ws, "fresh.io")  # not scored yet: neither hot nor cold

    def domains(query: str) -> list[str]:
        page = api.get(f"/api/companies?{query}")
        assert page.status_code == 200, page.text
        return [c["domain"] for c in page.json()["items"]]

    assert domains("hot=true") == ["hot.io"]
    assert sorted(domains("hot=false")) == ["edge.io", "warm.io"]
    assert sorted(domains("min_fit=75")) == ["edge.io", "hot.io"]
    assert domains("source=discovery") == ["hot.io"]
    assert sorted(domains("country=gb")) == ["edge.io", "hot.io"]
    assert domains("sort=fit") == ["hot.io", "edge.io", "warm.io", "fresh.io"]
    assert api.get("/api/companies?sort=sideways").status_code == 422
    assert api.get("/api/companies?min_fit=101").status_code == 422


def test_a_leads_page_can_carry_each_leads_person_address_status_and_cost(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    company_id = _lead(factory, ws, "pleo.io")
    bare = _lead(factory, ws, "empty.io")
    with factory(ws) as uow:
        uow.contacts.add(
            company_id, rank=2, source=ContactSource.SITE, full_name="Second Person",
            title="CTO", status=ContactStatus.ACTIVE,
        )  # fmt: skip
        first = uow.contacts.add(
            company_id, rank=1, source=ContactSource.SITE, full_name="Sara Okafor",
            title="Head of Finance", status=ContactStatus.ACTIVE,
        )  # fmt: skip
        uow.contacts.add(
            company_id, rank=0, source=ContactSource.SITE, full_name="Elsewhere",
            status=ContactStatus.NOT_HERE,
        )  # fmt: skip
        uow.emails.add(
            first.id, "s.okafor@pleo.io", Provenance.API_DATABASE, status=EmailStatus.VALID,
            is_primary=True,
        )  # fmt: skip
        for cost in (12_000, 19_000):
            uow.calls.record(
                provider="hunter", operation="find", request_hash=f"h{cost}",
                outcome=CallOutcome.HIT, cost_micro_usd=cost, credits_milli=cost // 10,
                company_id=company_id,
            )  # fmt: skip
        uow.commit()

    plain = api.get("/api/companies").json()["items"]
    assert all(item["summary"] is None for item in plain)  # only when asked for

    items = {i["id"]: i for i in api.get("/api/companies?include=summary").json()["items"]}
    assert items[company_id]["summary"] == {
        "contact_name": "Sara Okafor",
        "contact_title": "Head of Finance",
        "email_status": "valid",
        "credits_milli": 3_100,
    }
    assert items[bare]["summary"] == {
        "contact_name": None, "contact_title": None, "email_status": None, "credits_milli": 0,
    }  # fmt: skip


def test_daily_counts_leads_approvals_reviews_and_spend_and_the_review_streak(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    company_id = _lead(factory, ws, "acme.io")
    with factory(ws) as uow:
        for actor in ("operator", AUTO):
            uow.events.append(
                EntityType.MESSAGE, company_id, "status_changed", actor,
                {"from": "generated", "to": "approved"},
            )  # fmt: skip
        uow.events.append(
            EntityType.MESSAGE, company_id, "status_changed", "operator",
            {"from": "generated", "to": "rejected"},
        )  # fmt: skip
        uow.calls.record(
            provider="exa", operation="find", request_hash="x", outcome=CallOutcome.MISS,
            cost_micro_usd=5_000, credits_milli=500,
        )  # fmt: skip
        uow.commit()

    body = api.get("/api/reports/daily?days=7").json()
    assert len(body["days"]) == 7
    today = body["days"][-1]
    assert today["leads"] == 1
    assert today["approved"] == 2  # by a person and automatically
    assert today["reviewed"] == 2  # a person approved one and rejected one; AUTO is not a review
    assert today["credits_milli"] == 500
    assert body["review_streak"] == 1
    assert api.get("/api/reports/daily?days=0").status_code == 422


def test_fit_bands_cover_the_active_campaign_in_tens(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    for domain, fit in (("a.io", 95), ("b.io", 100), ("c.io", 61), ("d.io", None)):
        _lead(factory, ws, domain, fit=fit)
    body = api.get("/api/reports/fit").json()
    bands = {b["start"]: b["count"] for b in body["bands"]}
    assert list(bands) == list(range(0, 100, 10))
    assert bands[90] == 2 and bands[60] == 1  # 100 falls in the top band
    assert body["scored"] == 3 and body["unscored"] == 1


def test_the_discovery_plan_lists_every_source_and_says_why_one_is_skipped(api: Api) -> None:
    body = api.get("/api/runs/plan").json()
    names = [s["source"] for s in body["sources"]]
    assert sorted(names) == sorted(["yc_directory", "companies_house", "exa", "articles"])
    house = next(s for s in body["sources"] if s["source"] == "companies_house")
    assert house["suited"] is False and "SIC" in house["why_not"]
    # A plan never queues a run.
    assert api.get("/api/runs").json() == []
