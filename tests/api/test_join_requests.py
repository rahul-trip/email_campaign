"""Platform invitations, making or joining a workspace, and in-app notifications (Phase 6h)."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from outbound.api.deps import Services
from outbound.domain.enums import MembershipRole, PlatformRole
from outbound.providers.adapters.transactional_email import LogEmail
from tests.api.conftest import ADMIN, HEADERS, Api, add_user, sign_in

STAFF = "staff@platform.example"
NEWBIE = "newbie@elsewhere.example"
PASSWORD2 = "orbit lantern meadow plum kettle"


@pytest.fixture
def app(app_and_services: tuple[FastAPI, Services]) -> FastAPI:
    return app_and_services[0]


def invite_token(outbox: LogEmail) -> str:
    for email in reversed(outbox.sent):
        found = re.search(r"/invite/([\w-]+)", email.text)
        if found:
            return found.group(1)
    raise AssertionError("no invitation was sent")


def sign_up(app: FastAPI, outbox: LogEmail, email: str = NEWBIE) -> Api:
    """Staff invite ``email``; they accept, set a password, and are signed in."""
    staff = sign_in(app, STAFF)
    assert staff.post("/api/admin/invitations", json={"email": email}).status_code == 201
    client = TestClient(app)
    accepted = client.post(
        f"/api/auth/invitations/{invite_token(outbox)}/accept",
        json={"password": PASSWORD2, "name": "Newbie", "accept_terms": True},
        headers=HEADERS,
    )
    assert accepted.status_code == 200, accepted.text
    return Api(client)


def join_code(api: Api) -> str:
    return str(api.get("/api/team").json()["join_code"])


@pytest.fixture
def staff(app: FastAPI) -> None:
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)


# ------------------------------------------------------------------ invitations from staff


@pytest.mark.usefixtures("staff")
def test_a_platform_admin_invites_someone_to_outbound_with_no_workspace(
    app: FastAPI, outbox: LogEmail
) -> None:
    api = sign_up(app, outbox)
    me = api.get("/api/auth/me").json()
    assert me["user"]["email"] == NEWBIE
    assert me["workspaces"] == []  # nothing yet: they make one or ask to join


@pytest.mark.usefixtures("staff")
def test_the_invitation_page_says_it_is_to_outbound_not_a_workspace(
    app: FastAPI, outbox: LogEmail
) -> None:
    sign_in(app, STAFF).post("/api/admin/invitations", json={"email": NEWBIE})
    shown = TestClient(app).get(f"/api/auth/invitations/{invite_token(outbox)}").json()
    assert shown["workspace_name"] is None and shown["role"] is None


@pytest.mark.usefixtures("staff")
def test_staff_can_list_and_revoke_platform_invitations(app: FastAPI, outbox: LogEmail) -> None:
    staff = sign_in(app, STAFF)
    listed = staff.post("/api/admin/invitations", json={"email": NEWBIE}).json()
    assert [i["email"] for i in listed] == [NEWBIE]
    assert staff.delete(f"/api/admin/invitations/{listed[0]['id']}").json() == []
    gone = TestClient(app).post(
        f"/api/auth/invitations/{invite_token(outbox)}/accept",
        json={"password": PASSWORD2, "accept_terms": True},
        headers=HEADERS,
    )
    assert gone.status_code == 400


def test_a_workspace_member_or_admin_cannot_use_the_platform_invitation_route(
    app: FastAPI, api: Api
) -> None:
    assert api.post("/api/admin/invitations", json={"email": NEWBIE}).status_code == 403


@pytest.mark.usefixtures("staff")
def test_inviting_an_address_that_already_has_an_account_is_refused(app: FastAPI) -> None:
    refused = sign_in(app, STAFF).post("/api/admin/invitations", json={"email": ADMIN})
    assert refused.status_code == 409


# ------------------------------------------------------------------ making a workspace


@pytest.mark.usefixtures("staff")
def test_creating_a_workspace_makes_the_creator_its_admin(app: FastAPI, outbox: LogEmail) -> None:
    api = sign_up(app, outbox)
    made = api.post("/api/me/workspaces", json={"name": "Newbie Ltd"})
    assert made.status_code == 201 and made.json()["role"] == "admin"
    workspaces = api.get("/api/auth/me").json()["workspaces"]
    assert [(w["name"], w["role"]) for w in workspaces] == [("Newbie Ltd", "admin")]
    api.client.headers["X-Workspace-Id"] = made.json()["id"]
    assert api.get("/api/team").json()["join_code"]  # and it can invite and approve


def test_a_workspace_needs_a_name(api: Api) -> None:
    assert api.post("/api/me/workspaces", json={"name": "  "}).status_code == 422


# ------------------------------------------------------------------ asking to join


@pytest.mark.usefixtures("staff")
def test_a_join_request_tells_the_admins_and_an_approval_adds_the_person(
    app: FastAPI, api: Api, outbox: LogEmail, ws: str
) -> None:
    newbie = sign_up(app, outbox)
    asked = newbie.post("/api/me/join-requests", json={"code": join_code(api).lower()})
    assert asked.status_code == 201 and asked.json()["status"] == "pending"

    # the admin sees it in their notifications and on the team page
    notices = api.get("/api/me/notifications").json()
    assert notices["unread"] == 1 and notices["items"][0]["kind"] == "join_requested"
    assert notices["items"][0]["data"]["email"] == NEWBIE
    pending = api.get("/api/team").json()["requests"]
    assert [p["email"] for p in pending] == [NEWBIE]

    approved = api.post(
        f"/api/team/join-requests/{pending[0]['id']}/approve", json={"role": "admin"}
    )
    assert approved.status_code == 200 and approved.json()["requests"] == []
    assert {m["email"]: m["role"] for m in approved.json()["members"]}[NEWBIE] == "admin"

    # the admin's notice is read; the newcomer is told and is now in the workspace
    assert api.get("/api/me/notifications").json()["unread"] == 0
    told = newbie.get("/api/me/notifications").json()["items"]
    assert told[0]["kind"] == "join_approved" and told[0]["data"]["workspace_name"]
    assert [w["role"] for w in newbie.get("/api/auth/me").json()["workspaces"]] == ["admin"]


@pytest.mark.usefixtures("staff")
def test_approving_defaults_to_member_and_a_rejection_adds_no_one(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    first = sign_up(app, outbox, "first@elsewhere.example")
    first.post("/api/me/join-requests", json={"code": join_code(api)})
    second = sign_up(app, outbox, "second@elsewhere.example")
    second.post("/api/me/join-requests", json={"code": join_code(api)})
    ids = {r["email"]: r["id"] for r in api.get("/api/team").json()["requests"]}

    api.post(f"/api/team/join-requests/{ids['first@elsewhere.example']}/approve", json={})
    rejected = api.post(f"/api/team/join-requests/{ids['second@elsewhere.example']}/reject")
    roles = {m["email"]: m["role"] for m in rejected.json()["members"]}
    assert roles["first@elsewhere.example"] == "member"
    assert "second@elsewhere.example" not in roles
    assert second.get("/api/me/notifications").json()["items"][0]["kind"] == "join_rejected"
    assert second.get("/api/auth/me").json()["workspaces"] == []


@pytest.mark.usefixtures("staff")
def test_a_request_is_decided_once(app: FastAPI, api: Api, outbox: LogEmail) -> None:
    sign_up(app, outbox).post("/api/me/join-requests", json={"code": join_code(api)})
    request_id = api.get("/api/team").json()["requests"][0]["id"]
    assert api.post(f"/api/team/join-requests/{request_id}/reject").status_code == 200
    assert api.post(f"/api/team/join-requests/{request_id}/approve", json={}).status_code == 409


@pytest.mark.usefixtures("staff")
def test_asking_twice_or_when_already_in_is_refused(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    newbie = sign_up(app, outbox)
    code = join_code(api)
    assert newbie.post("/api/me/join-requests", json={"code": code}).status_code == 201
    assert newbie.post("/api/me/join-requests", json={"code": code}).status_code == 409
    assert api.post("/api/me/join-requests", json={"code": code}).status_code == 409  # a member


@pytest.mark.usefixtures("staff")
def test_a_wrong_code_finds_nothing_and_too_many_are_throttled(
    app: FastAPI, outbox: LogEmail
) -> None:
    newbie = sign_up(app, outbox)
    for _ in range(10):
        assert newbie.post("/api/me/join-requests", json={"code": "WRONG123"}).status_code == 404
    assert newbie.post("/api/me/join-requests", json={"code": "WRONG123"}).status_code == 429


@pytest.mark.usefixtures("staff")
def test_a_new_join_code_kills_the_old_one(app: FastAPI, api: Api, outbox: LogEmail) -> None:
    old = join_code(api)
    new = api.post("/api/team/join-code").json()["join_code"]
    assert new != old
    newbie = sign_up(app, outbox)
    assert newbie.post("/api/me/join-requests", json={"code": old}).status_code == 404
    assert newbie.post("/api/me/join-requests", json={"code": new}).status_code == 201


@pytest.mark.usefixtures("staff")
def test_a_member_cannot_decide_requests_or_change_the_code(
    app: FastAPI, api: Api, outbox: LogEmail, ws: str
) -> None:
    sign_up(app, outbox).post("/api/me/join-requests", json={"code": join_code(api)})
    request_id = api.get("/api/team").json()["requests"][0]["id"]
    add_user(app, "member@customer.example", ws, MembershipRole.MEMBER)
    member = sign_in(app, "member@customer.example", ws)
    assert member.post(f"/api/team/join-requests/{request_id}/approve", json={}).status_code == 403
    assert member.post("/api/team/join-code").status_code == 403


@pytest.mark.usefixtures("staff")
def test_a_person_sees_only_their_own_requests_and_notifications(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    newbie = sign_up(app, outbox)
    newbie.post("/api/me/join-requests", json={"code": join_code(api)})
    assert [r["status"] for r in newbie.get("/api/me/join-requests").json()] == ["pending"]
    assert api.get("/api/me/join-requests").json() == []
    assert newbie.get("/api/me/notifications").json()["items"] == []


def test_notifications_can_be_marked_read_one_by_one_or_all(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)
    for email in ("a@elsewhere.example", "b@elsewhere.example"):
        sign_up(app, outbox, email).post("/api/me/join-requests", json={"code": join_code(api)})
    items = api.get("/api/me/notifications").json()["items"]
    assert api.get("/api/me/notifications").json()["unread"] == 2
    api.post("/api/me/notifications/read", json={"id": items[0]["id"]})
    assert api.get("/api/me/notifications").json()["unread"] == 1
    api.post("/api/me/notifications/read", json={})
    assert api.get("/api/me/notifications").json()["unread"] == 0


def test_signing_in_is_needed_for_the_me_routes(app: FastAPI) -> None:
    anonymous = TestClient(app)
    assert anonymous.get("/api/me/notifications").status_code == 401
    assert (
        anonymous.post("/api/me/join-requests", json={"code": "X"}, headers=HEADERS).status_code
        == 401
    )
