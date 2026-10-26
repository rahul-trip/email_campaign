"""Vendor keys in the database (Phase 6d.4): masked, versioned, audited, and live without a
restart."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.domain.enums import PlatformRole
from outbound.services.vendors import LiveProviders, VendorService
from tests.api.conftest import ADMIN, Api, add_user, sign_in
from tests.api.test_admin import audited

STAFF = "keys@platform.example"
PLACEHOLDER = "placeholder-for-tests-abcd"


@pytest.fixture
def staff(app_and_services: tuple[FastAPI, Services]) -> Api:
    app, _ = app_and_services
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)
    return sign_in(app, STAFF)


def vendor(listing: dict, code: str) -> dict:  # type: ignore[type-arg]
    return next(v for v in listing["vendors"] if v["code"] == code)


def test_a_workspace_admin_cannot_see_vendors(api: Api) -> None:
    assert api.get("/api/admin/vendors").status_code == 403
    assert api.put("/api/admin/vendors/hunter/key", json={"key": PLACEHOLDER}).status_code == 403


def test_a_key_is_masked_versioned_and_never_listed_in_full(staff: Api) -> None:
    assert vendor(staff.get("/api/admin/vendors").json(), "hunter")["source"] != "database"
    out = staff.put("/api/admin/vendors/hunter/key", json={"key": PLACEHOLDER})
    assert out.status_code == 200
    assert PLACEHOLDER not in out.text
    row = vendor(out.json(), "hunter")
    assert row["key"] == "••••abcd" and row["version"] == 1 and row["source"] == "database"
    assert not row["can_roll_back"]
    row = vendor(
        staff.put("/api/admin/vendors/hunter/key", json={"key": PLACEHOLDER[:-4] + "wxyz"}).json(),
        "hunter",
    )
    assert row["version"] == 2 and row["can_roll_back"]
    back = vendor(staff.post("/api/admin/vendors/hunter/rollback").json(), "hunter")
    assert back["version"] == 1 and back["key"] == "••••abcd"


def test_revealing_a_key_is_audited(staff: Api, app_and_services: tuple[FastAPI, Services]) -> None:
    _, services = app_and_services
    staff.put("/api/admin/vendors/tavily/key", json={"key": PLACEHOLDER})
    assert staff.post("/api/admin/vendors/tavily/reveal").json() == {"key": PLACEHOLDER}
    assert len(audited(services, "vendor_key_revealed")) == 1
    assert len(audited(services, "vendor_key_replaced")) == 1
    assert staff.post("/api/admin/vendors/hunter/reveal").status_code == 422  # nothing stored


def test_unknown_vendor_and_short_keys_are_refused(staff: Api) -> None:
    assert staff.put("/api/admin/vendors/nope/key", json={"key": PLACEHOLDER}).status_code == 422
    assert staff.put("/api/admin/vendors/hunter/key", json={"key": "abc"}).status_code == 422


def test_a_change_reaches_the_adapters_without_a_restart(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    _, services = app_and_services
    service = VendorService(services.container.platform, services.container.settings)
    live = LiveProviders(service, lambda s: s.hunter_api_key.get_secret_value())
    before = live.get()
    assert before != PLACEHOLDER
    staff.put("/api/admin/vendors/hunter/key", json={"key": PLACEHOLDER})
    assert live.get() == PLACEHOLDER
    staff.put("/api/admin/vendors/hunter/paused", json={"paused": True})
    assert live.get() == ""
    staff.put("/api/admin/vendors/hunter/paused", json={"paused": False})
    assert live.get() == PLACEHOLDER


def test_llm_settings_override_the_environment(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    _, services = app_and_services
    out = staff.patch(
        "/api/admin/vendors/llm", json={"llm_model": "deepseek-x", "llm_max_tokens": 900}
    )
    assert out.json()["llm"]["llm_model"] == "deepseek-x"
    service = VendorService(services.container.platform, services.container.settings)
    settings, _ = service.effective_settings()
    assert settings.llm_model == "deepseek-x" and settings.llm_max_tokens == 900


def test_import_env_copies_once(app_and_services: tuple[FastAPI, Services]) -> None:
    from pydantic import SecretStr

    _, services = app_and_services
    base = services.container.settings.model_copy(update={"hunter_api_key": SecretStr(PLACEHOLDER)})
    service = VendorService(services.container.platform, base)
    assert service.import_env() == ["hunter"]
    assert service.import_env() == []
    assert ADMIN  # the fixture's admin exists; imported keys do not depend on it
