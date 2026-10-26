"""Vendor keys in the database (Phase 6d.4): masked, versioned, audited, and live without a
restart."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.config import Settings
from outbound.domain.enums import PlatformRole
from outbound.providers.adapters.transactional_email import LogEmail
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


def test_a_vendor_that_spent_its_cap_is_paused_once(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    from datetime import UTC, datetime

    from outbound.db.models import ProviderCallRow
    from outbound.domain.enums import CallOutcome

    _, services = app_and_services
    staff.put("/api/admin/vendors/hunter/key", json={"key": PLACEHOLDER})
    staff.put("/api/admin/vendors/hunter/cap", json={"cap_micro_usd": 1_000_000})
    service = VendorService(services.container.platform, services.container.settings)
    assert service.enforce_caps() == []  # nothing spent yet
    with services.container.uow(services.workspace_id) as uow:
        uow.session.add(
            ProviderCallRow(
                workspace_id=services.workspace_id, provider="hunter", operation="find",
                request_hash="x" * 64,
                outcome=CallOutcome.MISS, cost_micro_usd=1_500_000, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        uow.commit()
    assert service.enforce_caps() == ["hunter"]
    assert service.enforce_caps() == []  # already paused
    row = vendor(staff.get("/api/admin/vendors").json(), "hunter")
    assert (
        row["paused"] and row["spend_micro_usd"] == 1_500_000 and row["cap_micro_usd"] == 1_000_000
    )


# ---- testing a key, and a failing one


class _Search:
    name = "tavily"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.keys: list[str] = []

    def search(self, query: str, **kwargs: object) -> list[object]:
        if self.error:
            raise self.error
        return []


def test_the_test_button_makes_one_small_call_with_the_stored_key(
    staff: Api, app_and_services: tuple[FastAPI, Services], monkeypatch: pytest.MonkeyPatch
) -> None:
    from outbound.providers import keycheck
    from outbound.providers.errors import ProviderAuthError, ProviderError

    _, services = app_and_services
    seen: list[str] = []

    def fake_search(settings: Settings, client: object = None) -> _Search:
        seen.append(settings.tavily_api_key.get_secret_value())
        return _Search(errors.pop(0) if errors else None)

    monkeypatch.setattr(keycheck, "build_search", fake_search)
    staff.put("/api/admin/vendors/tavily/key", json={"key": PLACEHOLDER})
    errors: list[Exception | None] = [None, ProviderAuthError("tavily", "bad key", status_code=401)]

    ok = staff.post("/api/admin/vendors/tavily/test").json()
    assert ok["ok"] is True and "works" in ok["message"]
    assert seen == [PLACEHOLDER]  # the key as stored, not the environment's

    refused = staff.post("/api/admin/vendors/tavily/test").json()
    assert refused["ok"] is False and "rejected" in refused["message"]

    errors.append(ProviderError("tavily", "timed out", retryable=True))
    other = staff.post("/api/admin/vendors/tavily/test").json()
    assert other["ok"] is False and "timed out" in other["message"]

    never = staff.post("/api/admin/vendors/scrubby/test").json()
    assert never["ok"] is None and "first real use" in never["message"]
    assert len(audited(services, "vendor_key_tested")) == 4
    assert vendor(staff.get("/api/admin/vendors").json(), "scrubby")["can_test"] is False
    assert vendor(staff.get("/api/admin/vendors").json(), "tavily")["can_test"] is True


def test_staff_hear_once_a_day_when_a_vendor_keeps_refusing_the_key(
    staff: Api, app_and_services: tuple[FastAPI, Services], outbox: LogEmail
) -> None:
    from datetime import UTC, datetime

    from outbound.db.models import ProviderCallRow
    from outbound.domain.enums import CallOutcome
    from outbound.services.admin import AdminService
    from outbound.services.notices import NoticeService

    _, services = app_and_services
    c = services.container
    with c.uow(services.workspace_id) as uow:
        for n in range(3):
            uow.session.add(
                ProviderCallRow(
                    workspace_id=services.workspace_id, provider="hunter", operation="find",
                    request_hash=str(n) * 64, outcome=CallOutcome.ERROR,
                    response={"error": "ProviderAuthError"}, created_at=datetime.now(UTC),
                )
            )  # fmt: skip
        uow.session.add(  # a timeout is not a bad key
            ProviderCallRow(
                workspace_id=services.workspace_id, provider="tavily", operation="search",
                request_hash="t" * 64, outcome=CallOutcome.ERROR,
                response={"error": "ProviderError"}, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        uow.commit()
    assert vendor(staff.get("/api/admin/vendors").json(), "hunter")["key_refusals"] == 3
    assert vendor(staff.get("/api/admin/vendors").json(), "tavily")["key_refusals"] == 0
    notices = NoticeService(
        AdminService(c.platform, c.identity, c.uow),
        c.identity,
        outbox,
        "https://app.example",
    )
    assert notices.run()["staff"] >= 1
    sent = [m for m in outbox.sent if "hunter key" in m.subject]
    assert sent and "Vendors and keys" in sent[0].text
    before = len(outbox.sent)
    notices.run()
    assert len(outbox.sent) == before
