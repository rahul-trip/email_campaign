"""The four pay-as-you-go finders are wired into settings, the registry, prices and the console."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from outbound.config import Settings
from outbound.domain.vendors import BY_CODE
from outbound.providers.keycheck import FINDERS, can_test, check_key
from outbound.providers.pricing import DEFAULT_PRICES
from outbound.providers.registry import build_finder_chain, build_finder_named, configured_finders

NEW = ("anymailfinder", "prospeo", "icypeas", "generect")


def settings(**keys: str) -> Settings:
    update: dict[str, object] = {f"{n}_api_key": SecretStr(v) for n, v in keys.items()}
    return Settings(_env_file=None).model_copy(update=update)


def test_each_new_finder_is_a_vendor_with_a_key_setting_a_price_and_a_key_test() -> None:
    assert FINDERS == NEW
    for code in NEW:
        assert BY_CODE[code].role == "finder"  # the console manages its key, cap and pause
        assert hasattr(Settings(_env_file=None), BY_CODE[code].setting)
        assert (DEFAULT_PRICES[f"{code}:find"] or 0) > 0
        assert can_test(code)


def test_a_finder_with_a_key_can_be_chosen_in_the_chain_and_one_without_is_refused() -> None:
    keys = {name: name[0] * 12 for name in NEW}
    configured = configured_finders(settings(**keys))
    assert set(NEW) <= set(configured)
    chain = build_finder_chain(settings(**keys).model_copy(update={"finder_chain": ["prospeo"]}))
    assert [f.name for f in chain] == ["prospeo"]
    assert build_finder_named("generect", settings(**keys)).name == "generect"
    try:
        build_finder_named("icypeas", settings())
    except Exception as error:
        assert "not configured" in str(error)
    else:
        raise AssertionError("a finder with no key must not be built")


def test_the_console_key_test_asks_for_a_person_who_cannot_be_found_and_says_whether_it_works() -> (
    None
):
    def miss(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"email_status": "not_found", "credits_charged": 0})

    client = httpx.Client(transport=httpx.MockTransport(miss))
    good = check_key("anymailfinder", settings(anymailfinder="a" * 12), client)
    assert good.ok is True

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    bad = check_key(
        "anymailfinder",
        settings(anymailfinder="a" * 12),
        httpx.Client(transport=httpx.MockTransport(refused)),
    )
    assert bad.ok is False and "rejected" in bad.message
