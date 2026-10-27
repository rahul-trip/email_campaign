"""Phase 6b gate: every route declares its permission, and each role gets exactly that.

The walk calls every tenant route as an admin, a member, a superadmin looking in, and a
platform admin who is not a member. Path ids are made up, so an allowed call usually ends in
404 or 422; what matters is that it is not refused for the role, and that a refusal is.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from outbound.api import routers
from outbound.api.deps import Services
from outbound.domain.enums import MembershipRole, PlatformRole
from outbound.domain.permissions import ROLE_PERMISSIONS, Permission
from tests.api.conftest import ADMIN, PASSWORD, Api, add_user, sign_in

# Routes anyone may call, or that check something else (a signature, the session alone).
OPEN = {
    "/api/health",
    "/api/intake/webhook/{workspace_id}",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/logout-others",
    "/api/auth/me",
    "/api/auth/password/forgot",
    "/api/auth/password/reset",
    "/api/auth/password/change",
    # Public on purpose: a person who is not a user asks to leave the directory, by email link.
    "/api/auth/remove-my-data",
    "/api/auth/remove-my-data/confirm",
    "/api/auth/invitations/{token}",
    "/api/auth/invitations/{token}/accept",
    # A signed-in person's own account, before or beside any workspace: make one, ask to join
    # one, read their notifications. Each call acts only on the caller.
    "/api/me/workspaces",
    "/api/me/join-requests",
    "/api/me/notifications",
    "/api/me/notifications/read",
    # The provider's return page knows no workspace: the route finds it in the session's pending
    # sign-in and checks mailboxes.own there itself.
    "/api/mailboxes/oauth/finish",
}


def declared(route: APIRoute) -> Permission | None:
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        found = getattr(dependency.call, "permission", None)
        if found is not None:
            return Permission(found)
        stack.extend(dependency.dependencies)
    return None


def api_routes(app: FastAPI | None = None) -> list[tuple[str, str, Permission | None]]:
    """Every route of every module in ``outbound.api.routers``, so a new router is walked too."""
    found = []
    for module in pkgutil.iter_modules(routers.__path__):
        router = importlib.import_module(f"{routers.__name__}.{module.name}").router
        for route in router.routes:
            if isinstance(route, APIRoute):
                for method in sorted((route.methods or set()) - {"HEAD"}):
                    found.append((method, route.path, declared(route)))
    return found


@pytest.fixture
def app(app_and_services: tuple[FastAPI, Services]) -> FastAPI:
    return app_and_services[0]


def test_every_api_route_declares_a_permission_unless_it_is_open(app: FastAPI) -> None:
    missing = [
        f"{method} {path}"
        for method, path, permission in api_routes(app)
        if permission is None and path not in OPEN
    ]
    assert missing == []
    assert len(api_routes(app)) > 60  # the walk really saw the routers
    assert ("POST", "/api/team/invitations", Permission.TEAM_MANAGE) in api_routes(app)


def call(client: Api, method: str, path: str) -> Any:
    url = path.replace("{", "").replace("}", "")  # every path id becomes a made-up value
    if method in ("GET", "DELETE"):
        return getattr(client, method.lower())(url)
    return getattr(client, method.lower())(url, json={})


def refused(response: Any) -> bool:
    return bool(response.status_code == 403 and response.json()["code"] == "forbidden")


def tenant_routes(app: FastAPI) -> list[tuple[str, str, Permission]]:
    return [
        (m, p, perm)
        for m, p, perm in api_routes(app)
        if perm is not None and not p.startswith("/api/admin")
    ]


def test_a_member_does_the_work_but_not_the_admin_jobs(app: FastAPI, ws: str) -> None:
    add_user(app, "member@customer.example", ws, MembershipRole.MEMBER)
    member = sign_in(app, "member@customer.example")
    member_may = ROLE_PERMISSIONS[MembershipRole.MEMBER]
    wrong = []
    for method, path, permission in tenant_routes(app):
        response = call(member, method, path)
        if refused(response) == (permission in member_may):
            wrong.append(f"{method} {path} ({permission}): {response.status_code}")
    assert wrong == []


def test_an_admin_is_refused_nothing_in_the_workspace(api: Api) -> None:
    app: FastAPI = api.app  # type: ignore[assignment]
    wrong = [
        f"{method} {path}"
        for method, path, _ in tenant_routes(app)
        if refused(call(api, method, path))
    ]
    assert wrong == []


def test_a_superadmin_reads_any_workspace_but_writes_nothing(
    app: FastAPI, ws: str, container: Any
) -> None:
    add_user(app, "staff@platform.example", platform_role=PlatformRole.SUPERADMIN)
    staff = sign_in(app, "staff@platform.example", ws)
    wrong = []
    for method, path, permission in tenant_routes(app):
        response = call(staff, method, path)
        reads = permission.value.endswith(".read")
        if refused(response) == reads:
            wrong.append(f"{method} {path}: {response.status_code}")
    assert wrong == []
    assert staff.get("/api/companies").status_code == 200
    with container.identity() as ids:
        views = [e for e in ids.audit.recent() if e["action"] == "superadmin_viewed_workspace"]
    assert len(views) == 1  # once per session and workspace, not once per request


def test_the_superadmin_view_can_be_switched_off(app: FastAPI, ws: str) -> None:
    add_user(app, "staff@platform.example", platform_role=PlatformRole.SUPERADMIN)
    staff = sign_in(app, "staff@platform.example", ws)
    app.state.superadmin_enabled = False
    response = staff.get("/api/companies")
    assert response.status_code == 403 and response.json()["code"] == "not_a_member"


def test_a_platform_admin_does_not_see_inside_workspaces(app: FastAPI, ws: str) -> None:
    add_user(app, "ops@platform.example", platform_role=PlatformRole.ADMIN)
    ops = sign_in(app, "ops@platform.example", ws)
    response = ops.get("/api/companies")
    assert response.status_code == 403 and response.json()["code"] == "not_a_member"


def test_a_forged_workspace_header_reaches_nothing(api: Api, other_ws: str) -> None:
    api.client.headers["X-Workspace-Id"] = other_ws
    for path in ("/api/companies", "/api/review", "/api/settings/workspace"):
        response = api.get(path)
        assert response.status_code == 403 and response.json()["code"] == "not_a_member"
    api.client.headers["X-Workspace-Id"] = "no-such-workspace"
    assert api.get("/api/companies").status_code == 403


def test_someone_in_two_workspaces_must_say_which(app: FastAPI, ws: str, other_ws: str) -> None:
    add_user(app, ADMIN, other_ws, MembershipRole.MEMBER)
    both = sign_in(app, ADMIN)
    response = both.get("/api/companies")
    assert response.status_code == 400 and response.json()["code"] == "workspace_required"
    both.client.headers["X-Workspace-Id"] = ws
    assert both.get("/api/companies").status_code == 200
    both.client.headers["X-Workspace-Id"] = other_ws
    assert refused(both.put("/api/settings/workspace", json={}))  # only a member there


def test_a_removed_member_loses_access_at_once(app: FastAPI, ws: str, api: Api) -> None:
    member_id = add_user(app, "member@customer.example", ws, MembershipRole.MEMBER)
    member = sign_in(app, "member@customer.example")
    assert member.get("/api/companies").status_code == 200
    assert api.delete(f"/api/team/members/{member_id}").status_code == 200
    assert member.get("/api/companies").status_code in (400, 403)


def test_staff_only_routes_refuse_workspace_admins(api: Api) -> None:
    body = {"name": "Globex", "admin_email": "boss@globex.example"}
    response = api.post("/api/admin/customers", json=body)
    assert response.status_code == 403


def test_the_password_constant_is_strong_enough() -> None:
    from outbound.domain.passwords import password_problem

    assert password_problem(PASSWORD, email=ADMIN) is None


def test_an_anonymous_request_is_refused_before_any_permission(app: FastAPI) -> None:
    anonymous = TestClient(app)
    response = anonymous.get("/api/team")
    assert response.status_code == 401
