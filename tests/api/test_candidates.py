"""A run's discovered companies, and promoting one the screening left out."""

from __future__ import annotations

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CandidateVerdict
from outbound.services.runs import RunRequest, RunService
from tests.api.conftest import Api


def _found(factory: UnitOfWorkFactory, ws: str) -> tuple[str, str, str]:
    run = RunService(factory, ws).queue(RunRequest())
    with factory(ws) as uow:
        campaign = uow.campaigns.create("grid", ["CTO"])
        rejected = uow.candidates.add(
            campaign_id=campaign.id, run_id=run.id, name="Gridcast", name_key="gridcast",
            domain="gridcast.io", sources=["yc_directory"], screen_score=40, rank_score=40,
            verdict=CandidateVerdict.REJECTED, reason="too small",
        )  # fmt: skip
        unresolved = uow.candidates.add(
            campaign_id=campaign.id, run_id=run.id, name="Mystery Power", name_key="mystery power",
            verdict=CandidateVerdict.UNRESOLVED, screen_score=80, rank_score=80,
            reason="fits, but its website could not be confirmed",
        )  # fmt: skip
        uow.commit()
    return run.id, rejected.id, unresolved.id


def test_a_run_lists_the_companies_it_found_best_first(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    run_id, _, _ = _found(factory, ws)
    listed = api.get(f"/api/runs/{run_id}/candidates").json()
    assert [c["name"] for c in listed] == ["Mystery Power", "Gridcast"]
    assert listed[1]["verdict"] == "rejected" and listed[1]["sources"] == ["yc_directory"]


def test_a_company_the_screening_left_out_can_be_made_a_lead(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    _, rejected, unresolved = _found(factory, ws)
    promoted = api.post(f"/api/candidates/{rejected}/promote", json={})
    assert promoted.status_code == 200
    assert promoted.json()["verdict"] == "accepted" and promoted.json()["company_id"]
    with factory(ws) as uow:
        company = uow.companies.by_domain("gridcast.io")
    assert company is not None and company.id == promoted.json()["company_id"]
    # Once is enough.
    assert api.post(f"/api/candidates/{rejected}/promote", json={}).status_code == 422
    # One with no known website needs one.
    assert api.post(f"/api/candidates/{unresolved}/promote", json={}).status_code == 422
    done = api.post(f"/api/candidates/{unresolved}/promote", json={"domain": "mystery.energy"})
    assert done.status_code == 200 and done.json()["domain"] == "mystery.energy"
    assert api.post("/api/candidates/nope/promote", json={}).status_code == 404


def test_the_reports_say_where_good_leads_come_from(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    _found(factory, ws)
    rows = api.get("/api/reports/sources").json()
    assert rows == [
        {"source": "yc_directory", "found": 1, "leads": 0, "qualified": 0, "rate": 0.0,
         "days": 90},
    ]  # fmt: skip
