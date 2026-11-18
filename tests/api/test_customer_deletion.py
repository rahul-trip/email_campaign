"""Deleting a customer: closed at once, restorable for 30 days, then purged by the worker. The
members keep their accounts and ask the platform staff for a new workspace."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.domain.enums import CallOutcome, CompanySource, MembershipRole, PlatformRole
from outbound.services.admin import AdminService
from tests.api.conftest import ADMIN, Api, add_user, sign_in

STAFF = "ops@platform.example"
MEMBER = "member@customer.example"


@pytest.fixture
def staff(app_and_services: tuple[FastAPI, Services]) -> Api:
    app, _ = app_and_services
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)
    return sign_in(app, STAFF)


def name_of(staff: Api, ws: str) -> str:
    return str(staff.get(f"/api/admin/customers/{ws}").json()["row"]["name"])


def seed(services: Services) -> None:
    """A lead and a paid call in the test workspace."""
    with services.container.uow(services.workspace_id) as uow:
        company = uow.companies.create(domain="acme.example", source=CompanySource.MANUAL)
        uow.calls.record(
            provider="hunter", operation="find", request_hash="h", outcome=CallOutcome.HIT,
            cost_micro_usd=5_000, credits_milli=500, company_id=company.id,
        )  # fmt: skip
        uow.commit()


def admin_service(app: FastAPI, now: datetime | None = None) -> AdminService:
    service: AdminService = app.state.admin
    if now is not None:
        service._now = lambda: now
    return service


def test_deleting_needs_the_name_and_closes_the_workspace_at_once(
    staff: Api, api: Api, ws: str
) -> None:
    wrong = staff.post(f"/api/admin/customers/{ws}/delete", json={"confirm": "nope"})
    assert wrong.status_code == 422
    done = staff.post(f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws)})
    assert done.status_code == 200, done.text
    row = done.json()["row"]
    assert row["status"] == "pending_deletion" and row["deletion_due_at"]
    # members are signed out, and the workspace is closed to them
    assert api.get("/api/auth/me").status_code == 401
    member = sign_in(api.app, ADMIN, ws)  # type: ignore[arg-type]
    assert member.get("/api/team").status_code == 403
    me = member.get("/api/auth/me").json()
    assert me["workspaces"] == [] and me["needs_new_workspace"] is True
    attention = staff.get("/api/admin/overview").json()["attention"]
    assert any(a["kind"] == "deletion_due" and a["workspace_id"] == ws for a in attention)


def test_a_deletion_can_be_restored_before_it_is_due(staff: Api, ws: str) -> None:
    staff.post(f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws)})
    restored = staff.post(f"/api/admin/customers/{ws}/restore")
    assert restored.status_code == 200 and restored.json()["row"]["status"] == "active"
    assert restored.json()["row"]["deletion_due_at"] is None
    assert staff.post(f"/api/admin/customers/{ws}/restore").status_code == 409


def test_the_purge_waits_for_the_grace_period_then_keeps_only_the_books(
    app_and_services: tuple[FastAPI, Services], staff: Api, ws: str
) -> None:
    app, services = app_and_services
    seed(services)
    add_user(app, MEMBER, ws, MembershipRole.MEMBER)
    staff.post(f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws)})

    assert admin_service(app).purge_due() == []  # not due yet
    later = datetime.now(UTC) + timedelta(days=31)
    assert admin_service(app, later).purge_due() == [ws]

    with services.container.uow(ws) as uow:
        assert uow.companies.by_domain("acme.example") is None
        assert uow.campaigns.all() == []
    with services.container.platform() as p:
        found = p.workspaces.get(ws)
        assert found is not None and found.status.value == "deleted"
        # the cost of the call is still on the books, with no link to the lead
        assert p.figures.cost(later - timedelta(days=400), later)[ws] == 5_000
    # members keep their accounts
    emails = {u["email"] for u in staff.get("/api/admin/users").json()}
    assert {ADMIN, MEMBER} <= emails
    assert staff.post(f"/api/admin/customers/{ws}/restore").status_code == 409


def test_deleting_now_skips_the_grace_period(
    app_and_services: tuple[FastAPI, Services], staff: Api, ws: str
) -> None:
    done = staff.post(
        f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws), "now": True}
    )
    assert done.status_code == 200 and done.json()["row"]["status"] == "deleted"
    again = staff.post(
        f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws), "now": True}
    )
    assert again.status_code == 409


def test_a_former_member_asks_the_staff_for_a_new_workspace(
    app_and_services: tuple[FastAPI, Services], staff: Api, ws: str
) -> None:
    app, _ = app_and_services
    staff.post(
        f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws), "now": True}
    )
    person = sign_in(app, ADMIN)
    refused = person.post("/api/me/workspaces", json={"name": "Again Ltd"})
    assert refused.status_code == 403 and refused.json()["code"] == "ask_platform"

    assert person.get("/api/me/workspace-request").json() is None
    asked = person.post("/api/me/workspace-request", json={"name": "Again Ltd", "note": "please"})
    assert asked.status_code == 201 and asked.json()["name"] == "Again Ltd"
    assert person.post("/api/me/workspace-request", json={"name": "x"}).status_code == 409

    requests = staff.get("/api/admin/workspace-requests").json()
    assert [(r["email"], r["name"], r["note"]) for r in requests] == [
        (ADMIN, "Again Ltd", "please")
    ]
    attention = staff.get("/api/admin/overview").json()["attention"]
    assert any(a["kind"] == "workspace_request" for a in attention)

    user_id = requests[0]["user_id"]
    made = staff.post(
        f"/api/admin/workspace-requests/{user_id}/approve", json={"name": "Again Ltd"}
    )
    assert made.status_code == 201, made.text
    assert staff.get("/api/admin/workspace-requests").json() == []
    assert person.get("/api/me/workspace-request").json() is None
    mine = person.get("/api/auth/me").json()["workspaces"]
    assert [(w["name"], w["role"]) for w in mine] == [("Again Ltd", "admin")]


def test_a_request_can_be_dismissed(
    app_and_services: tuple[FastAPI, Services], staff: Api, ws: str
) -> None:
    app, _ = app_and_services
    staff.post(
        f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws), "now": True}
    )
    person = sign_in(app, ADMIN)
    person.post("/api/me/workspace-request", json={"name": "Again Ltd"})
    user_id = staff.get("/api/admin/workspace-requests").json()[0]["user_id"]
    assert staff.post(f"/api/admin/workspace-requests/{user_id}/dismiss").status_code == 204
    assert staff.get("/api/admin/workspace-requests").json() == []
    assert person.get("/api/me/workspace-request").json() is None


def test_customers_cannot_delete_or_handle_requests(api: Api, ws: str) -> None:
    assert api.post(f"/api/admin/customers/{ws}/delete", json={"confirm": "x"}).status_code == 403
    assert api.get("/api/admin/workspace-requests").status_code == 403


def test_someone_with_another_workspace_left_is_not_sent_to_the_staff(
    app_and_services: tuple[FastAPI, Services], staff: Api, ws: str
) -> None:
    app, _ = app_and_services
    person = sign_in(app, ADMIN)
    other = person.post("/api/me/workspaces", json={"name": "Second Ltd"})
    assert other.status_code == 201
    staff.post(
        f"/api/admin/customers/{ws}/delete", json={"confirm": name_of(staff, ws), "now": True}
    )
    me = sign_in(app, ADMIN).get("/api/auth/me").json()
    assert [w["name"] for w in me["workspaces"]] == ["Second Ltd"]
    assert me["needs_new_workspace"] is False
