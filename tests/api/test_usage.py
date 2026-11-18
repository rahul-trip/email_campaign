"""Plan, usage and credits through the API (Phase 6d): what the customer sees and can do."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.domain.enums import CallOutcome, MembershipRole, UsageStep
from tests.api.conftest import ADMIN, Api, add_user, sign_in


@pytest.fixture
def free(app_and_services: tuple[FastAPI, Services]) -> Services:
    """The test workspace, put on the Free plan (the fixture workspace is unlimited by default)."""
    _, services = app_and_services
    with services.container.platform() as p:
        p.plans.set_plan(
            services.workspace_id, "free", started_at=datetime.now(UTC) - timedelta(days=1),
            access_until=datetime.now(UTC) + timedelta(days=29),
        )  # fmt: skip
        p.commit()
    return services


def grant(services: Services, amount: int) -> None:
    with services.container.platform() as p:
        p.plans.add_grant(services.workspace_id, amount)
        p.commit()


def no_credits(services: Services) -> None:
    """The month's AI credits are all used."""
    with services.container.platform() as p:
        p.plans.add_override(services.workspace_id, "monthly_credits", 0)
        p.commit()


def add_leads(api: Api, count: int, start: int = 0) -> None:
    for n in range(start, start + count):
        assert (
            api.post("/api/targets", json={"website": f"lead{n}.com", "country": "UK"}).status_code
            == 200
        )


def test_usage_shows_the_plan_its_ai_credits_and_when_they_renew(api: Api, free: Services) -> None:
    with free.container.uow(free.workspace_id) as uow:
        uow.calls.record(
            provider="hunter", operation="find", request_hash="h", outcome=CallOutcome.HIT,
            cost_micro_usd=245_000, credits_milli=24_500,
        )  # fmt: skip
        uow.commit()
    grant(free, 50)
    body = api.get("/api/usage").json()
    assert (body["plan_code"], body["access"], body["engine"]) == ("free", "full", True)
    assert body["credits"] == {
        "monthly": 100,
        "granted": 50,
        "allowance": 150,
        "used_milli": 24_500,
        "remaining_milli": 125_500,
    }
    assert [(g["amount"], g["step"]) for g in body["grants"]] == [(50, None)]
    assert body["period_end"] > body["period_start"] and body["access_until"]
    assert (body["seats"], body["mailboxes"], body["active_campaigns"]) == (1, 1, 1)
    assert body["waiting_leads"] == {} and body["waiting_rows"] == 0


def test_a_lead_added_with_no_credits_left_waits_and_a_grant_resumes_it(
    api: Api, free: Services
) -> None:
    add_leads(api, 2)  # adding a lead uses no AI credits
    no_credits(free)
    later = api.post("/api/targets", json={"website": "later.com", "country": "UK"}).json()
    assert (
        later["rows"][0]["status"] == "pending"
        and "waiting for credits" in later["rows"][0]["reason"]
    )
    assert api.get("/api/usage").json()["waiting_rows"] == 1

    refused = api.post("/api/targets/resume")
    assert refused.json() == {"leads": 0, "rows": 0}  # no credits: nothing happens, no error
    refused_all = api.post("/api/companies/resume")
    assert refused_all.status_code == 409 and refused_all.json()["code"] == "no_credits"
    assert "Credits renew on" in refused_all.json()["detail"]

    grant(free, 100)
    assert api.post("/api/companies/resume").json() == {"leads": 0, "rows": 1}
    assert api.get("/api/usage").json()["waiting_rows"] == 0
    assert api.get("/api/companies?q=later.com").json()["total"] == 1


def test_a_lead_parked_mid_pipeline_is_listed_and_can_be_resumed_by_hand(
    api: Api, free: Services
) -> None:
    add_leads(api, 1)
    no_credits(free)
    with free.container.uow(free.workspace_id) as uow:
        company = uow.companies.search()[0][0]
        uow.companies.wait_for_credit(company.id, UsageStep.RESEARCH)
        uow.commit()
    waiting = api.get("/api/companies?waiting_for_credits=true").json()
    assert [(c["id"], c["credit_wait_step"]) for c in waiting["items"]] == [
        (company.id, "research")
    ]
    assert api.get("/api/companies?waiting_for_credits=false").json()["total"] == 0
    assert api.get("/api/usage").json()["waiting_leads"] == {"research": 1}

    refused = api.post(f"/api/companies/{company.id}/resume")
    assert refused.status_code == 409 and refused.json()["code"] == "no_credits"
    assert refused.json()["step"] == "research"
    grant(free, 100)
    assert api.post(f"/api/companies/{company.id}/resume").json() == {"leads": 1, "rows": 0}
    assert api.get("/api/companies?waiting_for_credits=true").json()["total"] == 0


def test_a_member_can_see_usage_and_ask_for_more_credits(
    app_and_services: tuple[FastAPI, Services], free: Services, ws: str
) -> None:
    app, _ = app_and_services
    add_user(app, "pat@customer.example", ws, MembershipRole.MEMBER)
    member = sign_in(app, "pat@customer.example")
    assert member.get("/api/usage").status_code == 200
    asked = member.post("/api/usage/request-credits", json={"amount": 500, "note": "pilot week"})
    assert asked.status_code == 202
    with free.container.identity() as ids:
        [entry] = [
            e for e in ids.audit.recent(workspace_id=ws) if e["action"] == "credits_requested"
        ]
    assert entry["data"] == {"amount": 500} and entry["note"] == "pilot week"
    empty = member.post("/api/usage/request-credits", json={})
    assert empty.status_code == 422  # say what you need


def test_past_its_access_date_the_workspace_is_read_only_but_can_still_ask(
    api: Api, free: Services
) -> None:
    add_leads(api, 1)
    with free.container.platform() as p:
        p.plans.set_access_until(free.workspace_id, datetime.now(UTC) - timedelta(days=1))
        p.commit()
    assert api.get("/api/companies").status_code == 200  # reading still works
    assert api.get("/api/usage").json()["access"] == "read_only"
    blocked = api.post("/api/targets", json={"website": "late.com"})
    assert blocked.status_code == 403 and blocked.json()["code"] == "access_ended"
    assert "ask your admin" in blocked.json()["detail"].lower()
    assert api.post("/api/runs", json={}).json()["code"] == "access_ended"
    assert api.post("/api/usage/request-credits", json={"note": "please extend"}).status_code == 202
    with free.container.platform() as p:  # an admin extends access
        p.plans.set_access_until(free.workspace_id, datetime.now(UTC) + timedelta(days=30))
        p.commit()
    assert (
        api.post("/api/targets", json={"website": "late.com", "country": "UK"}).status_code == 200
    )


def test_admin_credentials_are_unaffected_by_an_unrelated_workspaces_limits(
    api: Api, app_and_services: tuple[FastAPI, Services], other_ws: str
) -> None:
    _, services = app_and_services
    with services.container.platform() as p:
        p.plans.set_plan(other_ws, "free", started_at=datetime.now(UTC) - timedelta(days=1))
        p.plans.add_override(other_ws, "monthly_credits", 0)
        p.commit()
    add_leads(api, 7)  # this workspace has no plan row: unlimited
    assert ADMIN and api.get("/api/usage").json()["plan_code"] == "unlimited"
