"""A finder that ran out of credit is paused by itself and resumes when it has credit again; the
console shows what each vendor says is left. No call here reaches a vendor."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.db.models import ProviderCallRow
from outbound.domain.enums import CallOutcome
from outbound.providers.balances import Balance, balance
from outbound.services.vendors import VendorService

KEY = "k" * 12


def service(services: Services, answers: dict[str, Balance | None]) -> VendorService:
    c = services.container
    on = c.settings.model_copy(update={"vendor_balance_checks": True})
    return VendorService(c.platform, on, balance_of=lambda code, key: answers.get(code))


def refuse_for_credit(services: Services, provider: str) -> None:
    with services.container.uow(services.workspace_id) as uow:
        uow.session.add(
            ProviderCallRow(
                workspace_id=services.workspace_id, provider=provider, operation="find",
                request_hash="c" * 64, outcome=CallOutcome.ERROR,
                response={"error": "BudgetExceeded"}, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        uow.commit()


def status(vendors: VendorService, code: str):  # type: ignore[no-untyped-def]
    return next(v for v in vendors.statuses() if v.code == code)


def test_an_empty_finder_is_paused_and_comes_back_by_itself_when_it_has_credit(
    app_and_services: tuple[FastAPI, Services],
) -> None:
    _, services = app_and_services
    answers: dict[str, Balance | None] = {"hunter": Balance(0, "searches", "resets 2026-12-16")}
    vendors = service(services, answers)
    vendors.replace_key("hunter", KEY, by=None)
    assert vendors.handle_credit() == (["hunter"], [])
    shown = status(vendors, "hunter")
    assert (shown.paused, shown.paused_for_credit) == (True, True)
    assert (shown.balance, shown.balance_unit) == (0, "searches")
    settings, _ = vendors.effective_settings()
    assert "hunter" not in settings.finder_chain  # nothing calls it while it is empty
    assert vendors.handle_credit() == ([], [])  # already paused: nothing more to do

    answers["hunter"] = Balance(50, "searches")
    assert vendors.handle_credit() == ([], ["hunter"])
    assert not status(vendors, "hunter").paused
    assert "hunter" in vendors.effective_settings()[0].finder_chain


def test_a_balance_that_cannot_be_read_pauses_only_after_a_credit_refusal(
    app_and_services: tuple[FastAPI, Services],
) -> None:
    _, services = app_and_services
    vendors = service(services, {})  # no balance call answers
    vendors.replace_key("zerobounce", KEY, by=None)
    assert vendors.handle_credit() == ([], [])  # unknown is not zero
    refuse_for_credit(services, "zerobounce")
    assert vendors.handle_credit() == (["zerobounce"], [])


def test_a_refusal_is_ignored_when_the_vendor_says_it_has_credit(
    app_and_services: tuple[FastAPI, Services],
) -> None:
    _, services = app_and_services
    vendors = service(services, {"hunter": Balance(12, "searches")})
    vendors.replace_key("hunter", KEY, by=None)
    refuse_for_credit(services, "hunter")
    assert vendors.handle_credit() == ([], [])


def test_a_vendor_staff_paused_is_never_resumed_and_a_manual_resume_clears_the_mark(
    app_and_services: tuple[FastAPI, Services],
) -> None:
    _, services = app_and_services
    answers: dict[str, Balance | None] = {"hunter": Balance(0, "searches")}
    vendors = service(services, answers)
    vendors.replace_key("hunter", KEY, by=None)
    vendors.replace_key("zerobounce", KEY, by=None)
    vendors.pause("zerobounce", True, by="staff")  # a person's choice
    assert vendors.handle_credit() == (["hunter"], [])
    answers.update(hunter=Balance(5, "searches"), zerobounce=Balance(5, "credits"))
    assert vendors.handle_credit() == ([], ["hunter"])  # zerobounce stays as staff left it
    assert status(vendors, "zerobounce").paused
    vendors.pause("hunter", True, by="staff")
    vendors.pause("hunter", False, by="staff")
    assert not status(vendors, "hunter").paused_for_credit


def test_only_finders_are_paused_never_the_verifier(
    app_and_services: tuple[FastAPI, Services],
) -> None:
    _, services = app_and_services
    vendors = service(services, {"myemailverifier": Balance(0, "credits")})
    vendors.replace_key("myemailverifier", KEY, by=None)
    assert vendors.handle_credit() == ([], [])  # a paused verifier would stop every lead
    assert not status(vendors, "myemailverifier").paused


def test_a_vendor_with_no_key_is_not_paused(app_and_services: tuple[FastAPI, Services]) -> None:
    _, services = app_and_services
    vendors = service(services, {"hunter": Balance(0, "searches")})
    assert vendors.handle_credit() == ([], [])  # nothing to pause: it has no key at all


# ------------------------------------------------------------------ the vendors' own answers


def answering(body: Mapping[str, object], status_code: int = 200) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code, json=body))
    )


def test_hunter_gives_the_searches_left_and_when_they_reset() -> None:
    body = {"data": {"reset_date": "2026-12-16", "requests": {"searches": {"remaining": 0}}}}
    found = balance("hunter", KEY, answering(body))
    assert found == Balance(0, "searches", "resets 2026-12-16") and found.empty
    assert found.label() == "0 searches left, resets 2026-12-16"


def test_zerobounce_minus_one_is_a_refused_key_not_a_balance() -> None:
    assert balance("zerobounce", KEY, answering({"Credits": "-1"})) is None
    assert balance("zerobounce", KEY, answering({"Credits": "0"})) == Balance(0, "credits")
    assert balance("zerobounce", KEY, answering({"Credits": "1200"})) == Balance(1200, "credits")


def test_other_vendors_and_failures_are_unknown_never_zero() -> None:
    assert balance("myemailverifier", KEY, answering({"status": True, "credits": 100})) == Balance(
        100, "credits"
    )
    assert balance("orbisearch", KEY, answering({"credits": 99.8})) == Balance(99.8, "credits")
    assert balance("millionverifier", KEY, answering({"credits": 9990})) == Balance(9990, "credits")
    refused = {"result": "error", "error": "apikey_not_found"}
    assert balance("millionverifier", KEY, answering(refused)) is None
    assert balance("bounceban", KEY, answering({"available_credits": 42.5})) == Balance(
        42.5, "credits"
    )
    assert balance("bounceban", KEY, answering({"available_credits": -1})) is None  # unlimited
    assert balance("tavily", KEY, answering({})) is None  # no balance call
    assert balance("hunter", "", answering({})) is None  # no key
    assert balance("hunter", KEY, answering({"data": {}})) is None  # nothing readable

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert balance("hunter", KEY, httpx.Client(transport=httpx.MockTransport(broken))) is None
