"""The admin console API (Phase 6d): who may use it, what it changes, and that every change is
recorded. The customer's side of each change is checked through the customer's own API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from outbound.api.deps import Services
from outbound.domain.enums import MembershipRole, PlatformRole
from tests.api.conftest import ADMIN, Api, add_user, sign_in

STAFF = "ops@platform.example"
SUPER = "root@platform.example"


@pytest.fixture
def staff(app_and_services: tuple[FastAPI, Services]) -> Api:
    app, _ = app_and_services
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)
    return sign_in(app, STAFF)


@pytest.fixture
def superadmin(app_and_services: tuple[FastAPI, Services]) -> Api:
    app, _ = app_and_services
    add_user(app, SUPER, platform_role=PlatformRole.SUPERADMIN)
    return sign_in(app, SUPER)


@pytest.fixture
def free(app_and_services: tuple[FastAPI, Services]) -> Services:
    _, services = app_and_services
    with services.container.platform() as p:
        p.plans.set_plan(
            services.workspace_id, "free", started_at=datetime.now(UTC) - timedelta(days=1),
            access_until=datetime.now(UTC) + timedelta(days=29),
        )  # fmt: skip
        p.commit()
    return services


def audited(services: Services, action: str, workspace_id: str | None = None) -> list[dict]:  # type: ignore[type-arg]
    with services.container.identity() as ids:
        return [
            e
            for e in ids.audit.recent(workspace_id=workspace_id, limit=500)
            if e["action"] == action
        ]


# ------------------------------------------------------------------ who may use it


def test_only_platform_staff_use_the_console(
    api: Api, staff: Api, free: Services, app_and_services: tuple[FastAPI, Services]
) -> None:
    app, _ = app_and_services
    base = "/api/admin"
    paths = [
        f"{base}/{name}"
        for name in ("overview", "customers", "users", "plans", "settings", "audit")
    ]
    paths.append(f"{base}/customers/{free.workspace_id}")
    anonymous = TestClient(app)
    for path in paths:
        assert anonymous.get(path).status_code == 401
        assert api.get(path).status_code == 403  # a workspace admin is not platform staff
        assert staff.get(path).status_code == 200
    forbidden = api.patch(
        f"/api/admin/customers/{free.workspace_id}/status", json={"status": "paused"}
    )
    assert forbidden.status_code == 403


# ------------------------------------------------------------------ overview and customers


def test_the_overview_and_customer_list_show_use_without_any_lead_content(
    api: Api, staff: Api, free: Services
) -> None:
    for n in range(7):
        api.post("/api/targets", json={"website": f"lead{n}.com", "country": "UK"})
    overview = staff.get("/api/admin/overview").json()
    assert overview["customers"] >= 1 and overview["leads_added"] == 5 and overview["waiting"] == 0
    [row] = [c for c in staff.get("/api/admin/customers").json() if c["id"] == free.workspace_id]
    steps = {s["step"]: s for s in row["steps"]}
    assert (
        steps["manual"]["plan_limit"],
        steps["manual"]["used"],
        steps["manual"]["remaining"],
    ) == (5, 5, 0)
    assert row["plan_code"] == "free" and row["access"] == "full" and row["near_limit"] is True
    text = str(staff.get(f"/api/admin/customers/{free.workspace_id}").json())
    assert "lead0.com" not in text  # counts and settings, never the leads themselves


def test_customers_can_be_searched_and_filtered(staff: Api, free: Services) -> None:
    assert [c["id"] for c in staff.get("/api/admin/customers?q=zzz-nothing").json()] == []
    assert free.workspace_id in [
        c["id"] for c in staff.get("/api/admin/customers?plan=free").json()
    ]
    assert staff.get("/api/admin/customers?access=read_only").json() == []
    assert free.workspace_id not in [
        c["id"] for c in staff.get("/api/admin/customers?waiting=true").json()
    ]


# ------------------------------------------------------------------ the gate: limit, grant, resume


def test_the_sixth_lead_waits_and_a_grant_with_resume_now_adds_it(
    api: Api, staff: Api, free: Services
) -> None:
    for n in range(5):
        api.post("/api/targets", json={"website": f"lead{n}.com", "country": "UK"})
    api.post("/api/targets", json={"website": "sixth.com", "country": "UK"})
    assert api.get("/api/usage").json()["waiting_rows"] == 1

    granted = staff.post(
        f"/api/admin/customers/{free.workspace_id}/grants",
        json={"step": "manual", "amount": 3, "note": "pilot week"},
    )
    assert granted.status_code == 201
    body = granted.json()
    assert (body["grant"]["amount"], body["resumed_rows"], body["resumed_leads"]) == (3, 1, 0)
    assert api.get("/api/usage").json()["waiting_rows"] == 0
    assert api.get("/api/companies?q=sixth.com").json()["total"] == 1
    [entry] = audited(free, "credits_granted", free.workspace_id)
    assert entry["note"] == "pilot week" and entry["data"]["amount"] == 3


def test_a_grant_without_resume_now_leaves_waiting_work_for_the_tick(
    api: Api, staff: Api, free: Services
) -> None:
    for n in range(6):
        api.post("/api/targets", json={"website": f"lead{n}.com", "country": "UK"})
    made = staff.post(
        f"/api/admin/customers/{free.workspace_id}/grants",
        json={"step": "manual", "amount": 1, "resume_now": False},
    ).json()
    assert made["resumed_rows"] == 0 and api.get("/api/usage").json()["waiting_rows"] == 1
    assert staff.post(f"/api/admin/customers/{free.workspace_id}/resume").status_code == 200
    assert api.get("/api/usage").json()["waiting_rows"] == 0


def test_a_grant_is_validated_and_can_be_withdrawn(api: Api, staff: Api, free: Services) -> None:
    base = f"/api/admin/customers/{free.workspace_id}"
    assert staff.post(f"{base}/grants", json={"step": "manual", "amount": 0}).status_code == 422
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    expired = staff.post(f"{base}/grants", json={"step": "manual", "amount": 2, "expires_at": past})
    assert expired.status_code == 422
    made = staff.post(f"{base}/grants", json={"step": "manual", "amount": 4}).json()["grant"]
    assert api.get("/api/usage").json()["steps"][1]["granted"] == 4
    detail = staff.delete(f"{base}/grants/{made['id']}").json()
    assert detail["grants"][0]["revoked_at"] is not None
    assert [
        s["granted"] for s in api.get("/api/usage").json()["steps"] if s["step"] == "manual"
    ] == [0]
    assert staff.delete(f"{base}/grants/not-a-grant").status_code == 404
    assert len(audited(free, "grant_revoked", free.workspace_id)) == 1


def test_overrides_change_a_limit_at_once_and_unlimited_is_a_value(
    api: Api, staff: Api, free: Services
) -> None:
    base = f"/api/admin/customers/{free.workspace_id}"
    staff.put(f"{base}/overrides", json={"key": "limit.manual", "value": 20, "note": "agreed"})
    manual = next(s for s in api.get("/api/usage").json()["steps"] if s["step"] == "manual")
    assert (manual["limit"], manual["remaining"]) == (20, 20)
    detail = staff.put(f"{base}/overrides", json={"key": "limit.discovery", "value": None}).json()
    assert (
        next(s for s in api.get("/api/usage").json()["steps"] if s["step"] == "discovery")["limit"]
        is None
    )
    ids = {o["key"]: o["id"] for o in detail["overrides"]}
    staff.delete(f"{base}/overrides/{ids['limit.manual']}")
    assert (
        next(s for s in api.get("/api/usage").json()["steps"] if s["step"] == "manual")["limit"]
        == 5
    )
    assert (
        staff.put(f"{base}/overrides", json={"key": "limit.nonsense", "value": 1}).status_code
        == 422
    )
    assert staff.put(f"{base}/overrides", json={"key": "seats", "value": -1}).status_code == 422
    assert len(audited(free, "override_set", free.workspace_id)) == 2


# ------------------------------------------------------------------ plan, access and status


def test_changing_the_plan_is_audited_and_unknown_plans_are_refused(
    staff: Api, free: Services
) -> None:
    base = f"/api/admin/customers/{free.workspace_id}"
    assert staff.patch(f"{base}/plan", json={"plan": "nope"}).status_code == 422
    assert (
        staff.patch(f"{base}/plan", json={"plan": "unlimited", "note": "friend"}).status_code == 200
    )
    [entry] = audited(free, "plan_changed", free.workspace_id)
    assert entry["data"] == {"from": "free", "to": "unlimited"} and entry["note"] == "friend"


def test_extending_access_reopens_a_read_only_workspace_at_once(
    api: Api, staff: Api, free: Services
) -> None:
    base = f"/api/admin/customers/{free.workspace_id}"
    with free.container.platform() as p:
        p.plans.set_access_until(free.workspace_id, datetime.now(UTC) - timedelta(days=2))
        p.commit()
    assert api.post("/api/targets", json={"website": "late.com"}).json()["code"] == "access_ended"
    assert staff.get("/api/admin/customers").json()[0]["access"] in ("read_only", "full")
    assert staff.post(f"{base}/access", json={}).status_code == 422  # say how long
    reopened = staff.post(f"{base}/access", json={"days": 14, "note": "pilot"})
    assert reopened.status_code == 200 and reopened.json()["row"]["access"] == "full"
    assert (
        api.post("/api/targets", json={"website": "late.com", "country": "UK"}).status_code == 200
    )
    assert staff.post(f"{base}/access", json={"until": "2020-01-01T00:00:00Z"}).status_code == 422
    assert len(audited(free, "access_extended", free.workspace_id)) == 1


def test_a_suspended_customer_is_locked_out_and_can_be_reopened(
    api: Api, staff: Api, free: Services
) -> None:
    base = f"/api/admin/customers/{free.workspace_id}"
    assert (
        staff.patch(f"{base}/status", json={"status": "suspended", "note": "unpaid"}).status_code
        == 200
    )
    assert api.get("/api/companies").status_code in (
        401,
        403,
    )  # sessions ended; the workspace is closed
    again = TestClient(api.app)
    again.post(
        "/api/auth/login",
        json={"email": ADMIN, "password": "plum kettle orbit lantern meadow"},
        headers={"X-Requested-With": "outbound"},
    )
    assert (
        again.get("/api/companies", headers={"X-Workspace-Id": free.workspace_id}).status_code
        == 403
    )
    assert staff.patch(f"{base}/status", json={"status": "active"}).status_code == 200
    assert sign_in(api.app, ADMIN).get("/api/companies").status_code == 200  # type: ignore[arg-type]
    assert staff.patch(f"{base}/status", json={"status": "deleted"}).status_code == 422


def test_a_paused_engine_is_shown_to_the_customer_and_stops_runs(
    api: Api, staff: Api, free: Services
) -> None:
    base = f"/api/admin/customers/{free.workspace_id}"
    staff.patch(f"{base}/status", json={"status": "paused"})
    usage = api.get("/api/usage").json()
    assert usage["access"] == "full" and usage["engine"] is False
    staff.patch(f"{base}/status", json={"status": "active"})
    assert api.get("/api/usage").json()["engine"] is True


# ------------------------------------------------------------------ credit requests


def test_a_request_for_credits_is_open_until_a_grant_or_a_dismissal(
    api: Api, staff: Api, free: Services
) -> None:
    api.post("/api/usage/request-credits", json={"step": "manual", "note": "need more"})
    overview = staff.get("/api/admin/overview").json()
    assert [(a["kind"], a["workspace_id"]) for a in overview["attention"]] == [
        ("credit_request", free.workspace_id)
    ]
    assert (
        staff.get(f"/api/admin/customers/{free.workspace_id}").json()["requests"][0]["note"]
        == "need more"
    )
    staff.post(
        f"/api/admin/customers/{free.workspace_id}/grants", json={"step": "manual", "amount": 5}
    )
    assert staff.get("/api/admin/overview").json()["attention"] == []  # answered by the grant
    api.post("/api/usage/request-credits", json={"note": "again"})
    assert len(staff.get("/api/admin/overview").json()["attention"]) == 1
    staff.post(f"/api/admin/customers/{free.workspace_id}/dismiss-request")
    assert staff.get("/api/admin/overview").json()["attention"] == []


# ------------------------------------------------------------------ people


def test_users_are_listed_disabled_signed_out_and_never_by_themselves(
    api: Api, staff: Api, free: Services, app_and_services: tuple[FastAPI, Services]
) -> None:
    app, _ = app_and_services
    listed = {u["email"]: u for u in staff.get("/api/admin/users").json()}
    assert listed[ADMIN]["workspaces"] and listed[STAFF]["platform_role"] == "admin"
    assert [u["email"] for u in staff.get("/api/admin/users?q=ops").json()] == [STAFF]
    me = listed[STAFF]["id"]
    assert staff.post(f"/api/admin/users/{me}/disable").status_code == 409
    target = listed[ADMIN]["id"]
    assert staff.post(f"/api/admin/users/{target}/sign-out").json() == {"signed_out": 1}
    assert api.get("/api/companies").status_code == 401
    assert staff.post(f"/api/admin/users/{target}/disable").status_code == 204
    rejected = TestClient(app).post(
        "/api/auth/login",
        json={"email": ADMIN, "password": "plum kettle orbit lantern meadow"},
        headers={"X-Requested-With": "outbound"},
    )
    assert rejected.status_code == 403 and rejected.json()["code"] == "account_disabled"
    assert staff.post(f"/api/admin/users/{target}/enable").status_code == 204
    assert sign_in(app, ADMIN).get("/api/auth/me").status_code == 200


def test_only_a_superadmin_changes_platform_roles_and_the_last_one_stays(
    staff: Api, superadmin: Api, app_and_services: tuple[FastAPI, Services], ws: str
) -> None:
    app, _ = app_and_services
    user = add_user(app, "new@platform.example", ws, MembershipRole.MEMBER)
    assert (
        staff.put(f"/api/admin/users/{user}/platform-role", json={"role": "admin"}).status_code
        == 403
    )
    assert (
        superadmin.put(f"/api/admin/users/{user}/platform-role", json={"role": "admin"}).status_code
        == 204
    )
    me = next(u["id"] for u in superadmin.get("/api/admin/users").json() if u["email"] == SUPER)
    last = superadmin.put(f"/api/admin/users/{me}/platform-role", json={"role": "admin"})
    assert last.status_code == 409 and last.json()["code"] == "last_superadmin"
    assert (
        superadmin.put(f"/api/admin/users/{user}/platform-role", json={"role": None}).status_code
        == 204
    )


# ------------------------------------------------------------------ plans and settings


def test_plans_are_edited_with_a_version_check_and_the_default_is_chosen(
    staff: Api, free: Services
) -> None:
    catalog = staff.get("/api/admin/plans").json()
    assert [p["code"] for p in catalog["plans"]] == ["free"] and catalog["default_plan"] == "free"
    free_plan = catalog["plans"][0]
    assert free_plan["limits"]["manual"] == 5 and free_plan["customers"] == 1
    body = {"name": "Pro", "limits": {"manual": 100, "discovery": 50}, "seats": 10, "mailboxes": 5,
            "active_campaigns": None, "features": ["discovery", "directory_bypass"],
            "access_days": None, "version": catalog["version"]}  # fmt: skip
    saved = staff.put("/api/admin/plans/pro", json=body)
    assert saved.status_code == 200 and {p["code"] for p in saved.json()["plans"]} == {
        "free",
        "pro",
    }
    stale = staff.put("/api/admin/plans/pro", json=body)  # the version moved on
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    assert (
        staff.put(
            "/api/admin/plans/unlimited", json={**body, "version": saved.json()["version"]}
        ).status_code
        == 422
    )
    set_default = staff.put(
        "/api/admin/plans/default", json={"plan": "pro", "version": saved.json()["version"]}
    )
    assert set_default.json()["default_plan"] == "pro"
    assert (
        staff.put(
            "/api/admin/plans/default",
            json={"plan": "ghost", "version": set_default.json()["version"]},
        ).status_code
        == 422
    )
    assert len(audited(free, "plan_saved")) == 1


def test_a_customer_made_now_starts_on_the_default_plan(staff: Api, free: Services) -> None:
    catalog = staff.get("/api/admin/plans").json()
    body = {
        "name": "Pro",
        "limits": {"manual": 100},
        "access_days": 60,
        "version": catalog["version"],
    }
    saved = staff.put("/api/admin/plans/pro", json=body).json()
    staff.put("/api/admin/plans/default", json={"plan": "pro", "version": saved["version"]})
    made = staff.post(
        "/api/admin/customers", json={"name": "Initech", "admin_email": "boss@initech.example"}
    )
    assert made.status_code == 201
    row = next(
        c
        for c in staff.get("/api/admin/customers").json()
        if c["id"] == made.json()["workspace_id"]
    )
    assert row["plan_code"] == "pro"
    assert 59 <= (datetime.fromisoformat(row["access_until"]) - datetime.now(UTC)).days <= 60


def test_the_kill_switch_and_announcement_reach_every_customer(
    api: Api, staff: Api, free: Services
) -> None:
    current = staff.get("/api/admin/settings").json()
    changed = staff.patch(
        "/api/admin/settings",
        json={
            "version": current["version"],
            "kill_runs": True,
            "announcement": "Maintenance Sunday",
        },
    )
    assert changed.status_code == 200 and changed.json()["kill_runs"] is True
    usage = api.get("/api/usage").json()
    assert usage["engine"] is False and usage["announcement"] == "Maintenance Sunday"
    stale = staff.patch(
        "/api/admin/settings", json={"version": current["version"], "kill_runs": False}
    )
    assert stale.status_code == 409
    staff.patch(
        "/api/admin/settings", json={"version": changed.json()["version"], "kill_runs": False}
    )
    assert api.get("/api/usage").json()["engine"] is True
    [entry] = [
        e
        for e in audited(free, "platform_settings_changed")
        if "kill_runs" in e["data"] and e["data"]["kill_runs"]
    ]
    assert entry["data"]["announcement"] == "set"  # the text itself is not copied into the log


# ------------------------------------------------------------------ audit


def test_the_audit_log_filters_and_exports_without_formula_injection(
    api: Api, staff: Api, free: Services
) -> None:
    base = f"/api/admin/customers/{free.workspace_id}"
    staff.post(
        f"{base}/grants", json={"step": "manual", "amount": 2, "note": '=HYPERLINK("http://evil")'}
    )
    staff.patch(f"{base}/plan", json={"plan": "unlimited"})
    everything = staff.get("/api/admin/audit").json()
    assert {"credits_granted", "plan_changed"} <= {e["action"] for e in everything}
    grants = staff.get("/api/admin/audit?action=credits_granted").json()
    assert [e["action"] for e in grants] == ["credits_granted"] and grants[0]["actor"] == STAFF
    assert grants[0]["workspace"]
    assert staff.get(f"/api/admin/audit?workspace_id={free.workspace_id}").json()
    assert staff.get("/api/admin/audit?actor=no-such-user").json() == []
    csv_text = staff.get("/api/admin/audit.csv")
    assert csv_text.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in csv_text.text and ",=HYPERLINK" not in csv_text.text


# ---- a customer's people and mailboxes


def test_staff_change_a_members_role_remove_them_and_keep_the_last_admin(
    api: Api, staff: Api, services: Services, app_and_services: tuple[FastAPI, Services]
) -> None:
    app, _ = app_and_services
    add_user(app, "second@customer.example", services.workspace_id, MembershipRole.MEMBER)
    team = {m["email"]: m["user_id"] for m in api.get("/api/team").json()["members"]}
    other, me = team["second@customer.example"], team[ADMIN]
    base = f"/api/admin/customers/{services.workspace_id}/members"
    assert api.patch(f"{base}/{other}", json={"role": "admin"}).status_code == 403  # not staff
    assert staff.patch(f"{base}/{other}", json={"role": "admin"}).status_code == 204
    assert staff.delete(f"{base}/{other}").status_code == 204
    # Only one admin is left: the workspace keeps them.
    assert staff.delete(f"{base}/{me}").status_code == 409
    assert audited(services, "role_changed", services.workspace_id)
    assert audited(services, "member_removed", services.workspace_id)


def test_staff_can_make_a_customer_connect_a_mailbox_again(
    api: Api, staff: Api, services: Services
) -> None:
    with services.container.uow(services.workspace_id) as uow:
        box = uow.mailboxes.create("sam@customer.example", "customer.example")
        uow.commit()
    url = f"/api/admin/customers/{services.workspace_id}/mailboxes/{box.id}/reconnect"
    assert api.post(url).status_code == 403
    assert staff.post(url).status_code == 204
    with services.container.uow(services.workspace_id) as uow:
        assert [m.status.value for m in uow.mailboxes.all()] == ["needs_reconnect"]
    assert audited(services, "mailbox_reconnect_forced", services.workspace_id)
    assert staff.post(url.replace(box.id, "missing")).status_code == 404
