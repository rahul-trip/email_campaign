"""The mailbox routes (Phase 6c): who may act on which mailbox, and the OAuth entry points."""

from __future__ import annotations

from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.domain.enums import MailboxGateway, MembershipRole
from tests.api.conftest import ADMIN, Api, add_user, sign_in


def box(services: Services, address: str, owner: str | None = None) -> str:
    with services.container.uow(services.workspace_id) as uow:
        created = uow.mailboxes.create(address, address.rpartition("@")[2], owner_user_id=owner)
        uow.commit()
    return created.id


def test_mailboxes_are_listed_with_their_sender_and_default(
    api: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    _, services = app_and_services
    first = box(services, "sam@quantra.example")
    listed = api.get("/api/mailboxes").json()
    assert [(m["id"], m["is_default"], m["gateway"]) for m in listed] == [(first, True, "imap")]
    assert "credentials_ref" not in listed[0]  # not even the secret's name leaves the server


def test_only_imap_is_offered_until_the_sign_in_apps_are_set_up(api: Api) -> None:
    assert api.get("/api/mailboxes/options").json() == {"gateways": ["imap"]}
    started = api.post("/api/mailboxes/oauth/start", json={"gateway": "gmail"})
    assert started.status_code == 400 and started.json()["code"] == "not_available"


def test_finishing_a_sign_in_that_was_never_started_is_refused(api: Api) -> None:
    finished = api.post("/api/mailboxes/oauth/finish", json={"code": "c", "state": "s"})
    assert finished.status_code == 400 and finished.json()["code"] == "oauth_state"


def test_a_member_looks_after_their_own_mailbox_but_not_someone_elses(
    app_and_services: tuple[FastAPI, Services], ws: str
) -> None:
    app, services = app_and_services
    member_id = add_user(app, "pat@customer.example", ws, MembershipRole.MEMBER)
    member = sign_in(app, "pat@customer.example")
    theirs = box(services, "pat@quantra.example", owner=member_id)
    admins = box(services, "sam@quantra.example")
    assert member.post(f"/api/mailboxes/{theirs}/pause").json()["status"] == "paused"
    assert member.put(f"/api/mailboxes/{theirs}/sender", json={"signature_name": "Pat Kim"}).json()[
        "sender"
    ] == {"signature_name": "Pat Kim"}
    for call in (
        member.post(f"/api/mailboxes/{admins}/pause"),
        member.delete(f"/api/mailboxes/{admins}"),
        member.post(f"/api/mailboxes/{theirs}/default"),  # choosing the default is for admins
    ):
        assert call.status_code == 403
    admin = sign_in(app, ADMIN)
    assert admin.post(f"/api/mailboxes/{theirs}/default").json()["is_default"] is True
    assert admin.delete(f"/api/mailboxes/{theirs}").status_code == 204
    assert [m["id"] for m in admin.get("/api/mailboxes").json()] == [admins]


def test_a_mailbox_of_another_workspace_is_not_found(
    api: Api, app_and_services: tuple[FastAPI, Services], other_ws: str
) -> None:
    _, services = app_and_services
    with services.container.uow(other_ws) as uow:
        theirs = uow.mailboxes.create(
            "x@elsewhere.example", "elsewhere.example", gateway=MailboxGateway.IMAP
        )
        uow.commit()
    assert api.post(f"/api/mailboxes/{theirs.id}/pause").status_code == 404


def test_the_setup_report_is_served_to_every_member(
    api: Api, app_and_services: tuple[FastAPI, Services], ws: str
) -> None:
    app, _ = app_and_services
    add_user(app, "pat@customer.example", ws, MembershipRole.MEMBER)
    for who in (api, sign_in(app, "pat@customer.example")):
        body = who.get("/api/setup").json()
        assert {"items", "done", "next"} <= set(body) and body["done"] is False
        assert body["items"][0].keys() >= {"key", "title", "status", "detail", "where"}
