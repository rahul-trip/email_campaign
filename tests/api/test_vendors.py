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


def test_refusals_of_a_replaced_key_no_longer_count(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    """The old key was refused; once a new one is saved the warning clears at once, and only
    the new key's own refusals count."""
    from datetime import UTC, datetime, timedelta

    from outbound.db.models import ProviderCallRow
    from outbound.domain.enums import CallOutcome

    _, services = app_and_services
    c = services.container
    earlier = datetime.now(UTC) - timedelta(hours=2)

    def refused(n: int, at: datetime) -> None:
        with c.uow(services.workspace_id) as uow:
            for i in range(n):
                uow.session.add(
                    ProviderCallRow(
                        workspace_id=services.workspace_id, provider="scrubby",
                        operation="submit", request_hash=f"{at.timestamp()}{i}".ljust(64, "0"),
                        outcome=CallOutcome.ERROR, response={"error": "ProviderAuthError"},
                        created_at=at,
                    )
                )  # fmt: skip
            uow.commit()

    refused(3, earlier)
    assert vendor(staff.get("/api/admin/vendors").json(), "scrubby")["key_refusals"] == 3

    put = staff.put("/api/admin/vendors/scrubby/key", json={"key": "a-new-working-key"})
    assert put.status_code == 200
    assert vendor(put.json(), "scrubby")["key_refusals"] == 0

    refused(1, datetime.now(UTC) + timedelta(seconds=1))
    assert vendor(staff.get("/api/admin/vendors").json(), "scrubby")["key_refusals"] == 1


def test_a_vendor_takes_up_to_three_keys_and_each_slot_is_managed_on_its_own(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    _, services = app_and_services
    service = VendorService(services.container.platform, services.container.settings)
    keys = {slot: f"placeholder-slot-{slot}-key" for slot in (1, 2, 3)}
    for slot, key in keys.items():
        out = staff.put(f"/api/admin/vendors/tavily/key?slot={slot}", json={"key": key})
        assert out.status_code == 200
    listed = vendor(out.json(), "tavily")["keys"]
    assert [k["slot"] for k in listed] == [1, 2, 3]
    assert all(k["key"].endswith(keys[k["slot"]][-4:]) for k in listed)
    assert all(keys[k["slot"]] not in str(k) for k in listed)  # never in full

    settings, _ = service.effective_settings()
    assert settings.tavily_api_key.get_secret_value() == keys[1]
    assert [k.get_secret_value() for k in settings.vendor_key_pools["tavily"]] == list(
        keys.values()
    )

    assert (
        staff.put("/api/admin/vendors/tavily/key?slot=4", json={"key": keys[1]}).status_code == 422
    )
    assert staff.post("/api/admin/vendors/tavily/reveal?slot=2").json()["key"] == keys[2]

    out = staff.delete("/api/admin/vendors/tavily/key?slot=2")
    assert [k["slot"] for k in vendor(out.json(), "tavily")["keys"]] == [1, 3]
    assert staff.delete("/api/admin/vendors/tavily/key?slot=2").status_code == 422
    out = staff.post("/api/admin/vendors/tavily/rollback?slot=2")
    assert [k["slot"] for k in vendor(out.json(), "tavily")["keys"]] == [1, 2, 3]
    assert audited(services, "vendor_key_removed")


def test_one_key_left_means_no_pool(staff: Api, app_and_services: tuple[FastAPI, Services]) -> None:
    _, services = app_and_services
    service = VendorService(services.container.platform, services.container.settings)
    staff.put("/api/admin/vendors/exa/key?slot=2", json={"key": "placeholder-exa-two"})
    settings, _ = service.effective_settings()
    assert settings.exa_api_key.get_secret_value() == "placeholder-exa-two"
    assert "exa" not in settings.vendor_key_pools


def test_staff_see_a_vendor_out_of_credit_in_the_admin_bell_once_a_day(
    staff: Api, app_and_services: tuple[FastAPI, Services], outbox: LogEmail
) -> None:
    # Seen on 2026-11-18: Tavily said "plan or pay-as-you-go limit reached" and nobody was told.
    from datetime import UTC, datetime

    from outbound.db.models import ProviderCallRow
    from outbound.domain.enums import CallOutcome
    from outbound.services.admin import AdminService
    from outbound.services.notices import NoticeService

    _, services = app_and_services
    c = services.container
    with c.uow(services.workspace_id) as uow:
        uow.session.add(
            ProviderCallRow(
                workspace_id=services.workspace_id, provider="tavily", operation="search",
                request_hash="c" * 64, outcome=CallOutcome.ERROR,
                response={"error": "BudgetExceeded"}, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        uow.commit()
    notices = NoticeService(
        AdminService(c.platform, c.identity, c.uow), c.identity, outbox, "https://app.example"
    )
    notices.run()
    assert [m for m in outbox.sent if m.subject == "tavily is out of credit"]
    bell = staff.get("/api/me/notifications").json()
    alerts = [n for n in bell["items"] if n["kind"] == "platform_alert"]
    assert len(alerts) == 1 and alerts[0]["data"]["link"] == "/admin/vendors"
    assert "out of credit" in alerts[0]["data"]["title"] and bell["unread"] >= 1
    notices.run()  # the same day: not again
    bell = staff.get("/api/me/notifications").json()
    assert len([n for n in bell["items"] if n["kind"] == "platform_alert"]) == 1


def test_a_crash_is_an_alert_for_staff_at_most_hourly_and_never_for_customers(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    from datetime import UTC, datetime

    from outbound.services.staff_alerts import StaffAlerts

    _, services = app_and_services
    now = datetime(2026, 11, 18, 9, 5, tzinfo=UTC)
    alerts = StaffAlerts(services.container.identity, now=lambda: now)
    assert alerts.error("a run", RuntimeError("boom"), detail="Run r1.") == 1
    assert alerts.error("a run", RuntimeError("again")) == 0  # same place, error and hour
    items = staff.get("/api/me/notifications").json()["items"]
    crash = [n for n in items if n["kind"] == "platform_alert"]
    assert len(crash) == 1 and "RuntimeError in a run" in crash[0]["data"]["text"]
    customer = sign_in(app_and_services[0], ADMIN)
    assert not [
        n for n in customer.get("/api/me/notifications").json()["items"]
        if n["kind"] == "platform_alert"
    ]  # fmt: skip


def test_an_alert_that_cannot_be_written_does_not_break_the_caller() -> None:
    from outbound.services.staff_alerts import StaffAlerts

    def broken():  # type: ignore[no-untyped-def]
        raise RuntimeError("database away")

    assert StaffAlerts(broken).error("the worker", ValueError("x")) == 0  # type: ignore[arg-type]


def test_an_unexpected_server_error_reaches_staff_in_the_admin_bell(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    app, _ = app_and_services

    def boom() -> None:
        raise KeyError("a bug")

    app.router.routes.insert(0, APIRoute("/api/boom", boom, methods=["GET"]))
    answer = TestClient(app, raise_server_exceptions=False).get("/api/boom")
    assert answer.status_code == 500 and "Reference" in answer.json()["detail"]
    crash = [
        n for n in staff.get("/api/me/notifications").json()["items"]
        if n["kind"] == "platform_alert"
    ]  # fmt: skip
    assert len(crash) == 1 and "KeyError in the server (GET /api/boom)" in crash[0]["data"]["text"]
