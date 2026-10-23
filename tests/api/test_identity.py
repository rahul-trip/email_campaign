"""Phase 6b: invitations, password resets, the team page and creating a customer."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from outbound.api.deps import Services
from outbound.domain.enums import MembershipRole, PlatformRole, UserStatus
from outbound.providers.adapters.transactional_email import LogEmail
from tests.api.conftest import ADMIN, HEADERS, PASSWORD, Api, add_user, sign_in

NEW_PASSWORD = "violet harbour quietly sixteen"
PAST = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def app(app_and_services: tuple[FastAPI, Services]) -> FastAPI:
    return app_and_services[0]


def link_token(outbox: LogEmail, kind: str) -> str:
    """The token in the last link of ``kind`` ("invite" or "reset") the app emailed."""
    pattern = r"/invite/([\w-]+)" if kind == "invite" else r"reset-password\?token=([\w-]+)"
    for email in reversed(outbox.sent):
        found = re.search(pattern, email.text)
        if found:
            return found.group(1)
    raise AssertionError(f"no {kind} link was sent")


def accept(app: FastAPI, token: str, **body: object):  # type: ignore[no-untyped-def]
    client = TestClient(app)
    return client, client.post(f"/api/auth/invitations/{token}/accept", json=body, headers=HEADERS)


# ------------------------------------------------------------------ invitations


def test_an_admin_invites_and_the_new_member_sets_a_password_and_is_signed_in(
    app: FastAPI, api: Api, outbox: LogEmail, ws: str
) -> None:
    team = api.post("/api/team/invitations", json={"email": "Pat@Customer.example"})
    assert team.status_code == 201
    assert [i["email"] for i in team.json()["invitations"]] == ["pat@customer.example"]
    assert outbox.sent[-1].to == "pat@customer.example"
    token = link_token(outbox, "invite")

    shown = TestClient(app).get(f"/api/auth/invitations/{token}").json()
    assert shown["role"] == "member" and shown["has_account"] is False

    client, joined = accept(app, token, name="Pat", password=NEW_PASSWORD, accept_terms=True)
    assert joined.status_code == 200, joined.text
    assert [(w["id"], w["role"]) for w in joined.json()["workspaces"]] == [(ws, "member")]
    assert client.get("/api/companies").status_code == 200  # signed in by accepting

    members = {m["email"]: m["role"] for m in api.get("/api/team").json()["members"]}
    assert members == {ADMIN: "admin", "pat@customer.example": "member"}
    assert api.get("/api/team").json()["invitations"] == []
    # the link worked once
    assert accept(app, token, password=NEW_PASSWORD, accept_terms=True)[1].status_code == 400


def test_accepting_needs_the_terms_and_a_long_enough_password(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    api.post("/api/team/invitations", json={"email": "pat@customer.example"})
    token = link_token(outbox, "invite")
    no_terms = accept(app, token, password=NEW_PASSWORD)[1]
    assert no_terms.status_code == 422 and no_terms.json()["code"] == "terms_required"
    short = accept(app, token, password="short one", accept_terms=True)[1]
    assert short.status_code == 422 and short.json()["code"] == "weak_password"
    assert accept(app, token, password=NEW_PASSWORD, accept_terms=True)[1].status_code == 200


def test_someone_with_an_account_joins_by_signing_in_as_the_invited_address(
    app: FastAPI, api: Api, outbox: LogEmail, ws: str, other_ws: str
) -> None:
    add_user(app, "pat@customer.example", other_ws)
    api.post("/api/team/invitations", json={"email": "pat@customer.example", "role": "admin"})
    token = link_token(outbox, "invite")
    assert TestClient(app).get(f"/api/auth/invitations/{token}").json()["has_account"] is True

    anonymous = accept(app, token)[1]
    assert anonymous.status_code == 403 and anonymous.json()["code"] == "sign_in_first"
    someone_else = sign_in(app, ADMIN)
    wrong = someone_else.post(f"/api/auth/invitations/{token}/accept", json={})
    assert wrong.status_code == 403

    pat = sign_in(app, "pat@customer.example")
    joined = pat.post(f"/api/auth/invitations/{token}/accept", json={})
    assert joined.status_code == 200
    roles = {w["id"]: w["role"] for w in joined.json()["workspaces"]}
    assert roles == {ws: "admin", other_ws: "admin"}


def test_a_new_invitation_replaces_the_old_and_a_revoked_one_is_dead(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    api.post("/api/team/invitations", json={"email": "pat@customer.example"})
    first = link_token(outbox, "invite")
    team = api.post("/api/team/invitations", json={"email": "pat@customer.example"}).json()
    second = link_token(outbox, "invite")
    assert len(team["invitations"]) == 1
    assert TestClient(app).get(f"/api/auth/invitations/{first}").status_code == 400

    invite_id = team["invitations"][0]["id"]
    api.post(f"/api/team/invitations/{invite_id}/resend")
    third = link_token(outbox, "invite")
    assert third != second
    assert TestClient(app).get(f"/api/auth/invitations/{second}").status_code == 400

    assert api.delete(f"/api/team/invitations/{invite_id}").json()["invitations"] == []
    assert TestClient(app).get(f"/api/auth/invitations/{third}").status_code == 400


def test_inviting_someone_already_in_the_team_is_refused(api: Api) -> None:
    response = api.post("/api/team/invitations", json={"email": ADMIN})
    assert response.status_code == 409 and response.json()["code"] == "already_member"


def test_a_member_cannot_manage_the_team(app: FastAPI, ws: str) -> None:
    add_user(app, "member@customer.example", ws, MembershipRole.MEMBER)
    member = sign_in(app, "member@customer.example")
    assert member.get("/api/team").status_code == 200
    invite = member.post("/api/team/invitations", json={"email": "x@customer.example"})
    assert invite.status_code == 403


# ------------------------------------------------------------------ roles


def test_the_last_admin_cannot_leave_or_step_down(app: FastAPI, api: Api, ws: str) -> None:
    me = api.get("/api/auth/me").json()["user"]["id"]
    demote = api.patch(f"/api/team/members/{me}", json={"role": "member"})
    assert demote.status_code == 409 and demote.json()["code"] == "last_admin"
    assert api.delete(f"/api/team/members/{me}").status_code == 409

    other = add_user(app, "second@customer.example", ws, MembershipRole.MEMBER)
    assert api.patch(f"/api/team/members/{other}", json={"role": "admin"}).status_code == 200
    assert api.patch(f"/api/team/members/{me}", json={"role": "member"}).status_code == 200


def test_a_member_of_another_workspace_cannot_be_changed_from_this_one(
    app: FastAPI, api: Api, other_ws: str
) -> None:
    stranger = add_user(app, "stranger@elsewhere.example", other_ws)
    response = api.patch(f"/api/team/members/{stranger}", json={"role": "member"})
    assert response.status_code == 404


# ------------------------------------------------------------------ passwords


def test_a_forgotten_password_is_reset_by_a_single_use_link(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    anonymous = TestClient(app)
    asked = anonymous.post("/api/auth/password/forgot", json={"email": ADMIN}, headers=HEADERS)
    unknown = anonymous.post(
        "/api/auth/password/forgot", json={"email": "nobody@x.example"}, headers=HEADERS
    )
    assert asked.status_code == unknown.status_code == 202
    assert asked.json() == unknown.json()  # the answer does not reveal who has an account
    assert [e.to for e in outbox.sent] == [ADMIN]
    token = link_token(outbox, "reset")

    reset = anonymous.post(
        "/api/auth/password/reset",
        json={"token": token, "password": NEW_PASSWORD},
        headers=HEADERS,
    )
    assert reset.status_code == 200
    assert anonymous.get("/api/companies").status_code == 200  # signed in by the reset
    assert api.get("/api/companies").status_code == 401  # every other session ended
    again = anonymous.post(
        "/api/auth/password/reset", json={"token": token, "password": NEW_PASSWORD},
        headers=HEADERS,
    )  # fmt: skip
    assert again.status_code == 400
    old = TestClient(app).post(
        "/api/auth/login", json={"email": ADMIN, "password": PASSWORD}, headers=HEADERS
    )
    assert old.status_code == 401


def test_changing_the_password_needs_the_current_one_and_signs_out_elsewhere(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    elsewhere = sign_in(app, ADMIN)
    wrong = api.post(
        "/api/auth/password/change",
        json={"current_password": "not it at all, sorry", "new_password": NEW_PASSWORD},
    )
    assert wrong.status_code == 400
    changed = api.post(
        "/api/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204
    assert api.get("/api/companies").status_code == 200  # this browser stays signed in
    assert elsewhere.get("/api/companies").status_code == 401
    assert outbox.sent[-1].to == ADMIN  # told about it


def test_signing_out_other_browsers_keeps_this_one(app: FastAPI, api: Api) -> None:
    elsewhere = sign_in(app, ADMIN)
    assert api.post("/api/auth/logout-others").json() == {"signed_out": 1}
    assert api.get("/api/companies").status_code == 200
    assert elsewhere.get("/api/companies").status_code == 401


# ------------------------------------------------------------------ the platform's staff


def test_platform_staff_create_a_customer_and_invite_its_first_admin(
    app: FastAPI, outbox: LogEmail
) -> None:
    add_user(app, "ops@platform.example", platform_role=PlatformRole.ADMIN)
    ops = sign_in(app, "ops@platform.example")
    created = ops.post(
        "/api/admin/customers",
        json={
            "name": "Globex Ltd",
            "website": "globex.example",
            "admin_email": "boss@globex.example",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["slug"] == "globex-ltd" and body["invited"] == "boss@globex.example"

    token = link_token(outbox, "invite")
    _, joined = accept(app, token, password=NEW_PASSWORD, accept_terms=True)
    assert [(w["slug"], w["role"]) for w in joined.json()["workspaces"]] == [
        ("globex-ltd", "admin")
    ]
    with app.state.container.platform() as platform:
        globex = platform.workspaces.by_slug("globex-ltd")
    assert globex is not None and globex.status.value == "active"
    assert globex.sender_profile.get("domain") == "globex.example"
    assert ops.get("/api/companies").status_code == 400  # staff have no workspace of their own


def test_me_lists_every_workspace_for_a_superadmin_with_no_role_in_them(
    app: FastAPI, ws: str
) -> None:
    add_user(app, "staff@platform.example", platform_role=PlatformRole.SUPERADMIN)
    me = sign_in(app, "staff@platform.example").get("/api/auth/me").json()
    assert me["user"]["platform_role"] == "superadmin"
    assert {w["id"]: w["role"] for w in me["workspaces"]}[ws] is None


# ------------------------------------------------------------------ expiry and disabled accounts


def expire_links(app: FastAPI) -> None:
    with app.state.container.identity() as ids:
        ids.session.execute(text("UPDATE auth_tokens SET expires_at = :past"), {"past": PAST})
        ids.commit()


def test_an_expired_invitation_or_reset_link_is_refused(
    app: FastAPI, api: Api, outbox: LogEmail
) -> None:
    api.post("/api/team/invitations", json={"email": "pat@customer.example"})
    invite = link_token(outbox, "invite")
    TestClient(app).post("/api/auth/password/forgot", json={"email": ADMIN}, headers=HEADERS)
    reset = link_token(outbox, "reset")
    expire_links(app)
    assert accept(app, invite, password=NEW_PASSWORD, accept_terms=True)[1].status_code == 400
    refused = TestClient(app).post(
        "/api/auth/password/reset", json={"token": reset, "password": NEW_PASSWORD},
        headers=HEADERS,
    )  # fmt: skip
    assert refused.status_code == 400 and refused.json()["code"] == "link_invalid"


def test_a_disabled_account_is_signed_out_and_cannot_sign_in(app: FastAPI, api: Api) -> None:
    me = api.get("/api/auth/me").json()["user"]["id"]
    with app.state.container.identity() as ids:
        ids.users.set_status(me, UserStatus.DISABLED)
        ids.commit()
    assert api.get("/api/companies").status_code == 401
    again = TestClient(app).post(
        "/api/auth/login", json={"email": ADMIN, "password": PASSWORD}, headers=HEADERS
    )
    assert again.status_code == 403 and again.json()["code"] == "account_disabled"
