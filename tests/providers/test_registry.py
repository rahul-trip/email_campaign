from __future__ import annotations

import pytest

from outbound.config import Settings
from outbound.providers.adapters.hunter import HunterFinder
from outbound.providers.adapters.zerobounce import ZeroBounceFinder
from outbound.providers.errors import ProviderAuthError
from outbound.providers.registry import (
    build_finder_chain,
    build_resolver,
    build_verifier,
    configured_finders,
    configured_resolvers,
    configured_verifiers,
)


def settings(**values: object) -> Settings:
    """Settings that ignore any real ``.env`` so a developer's keys never leak into a test."""
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_nothing_is_configured_without_keys() -> None:
    blank = settings()
    assert configured_finders(blank) == {}
    assert configured_verifiers(blank) == {}
    assert configured_resolvers(blank) == {}


def test_only_adapters_with_credentials_are_returned() -> None:
    s = settings(hunter_api_key="h", orbisearch_api_key="o")
    assert sorted(configured_finders(s)) == ["hunter"]
    assert sorted(configured_verifiers(s)) == ["hunter", "orbisearch"]


def test_scrubby_needs_both_a_key_and_a_base_url() -> None:
    assert configured_resolvers(settings(scrubby_api_key="s")) == {}
    configured = configured_resolvers(
        settings(scrubby_api_key="s", scrubby_base_url="https://x.test")
    )
    assert sorted(configured) == ["scrubby"]


def test_the_finder_chain_is_built_in_the_configured_order() -> None:
    s = settings(hunter_api_key="h", zerobounce_api_key="z", finder_chain="zerobounce, hunter")
    chain = build_finder_chain(s)
    assert [type(f) for f in chain] == [ZeroBounceFinder, HunterFinder]


def test_the_chain_can_be_set_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINDER_CHAIN", "zerobounce,hunter")
    assert Settings(_env_file=None).finder_chain == ["zerobounce", "hunter"]


def test_asking_for_an_unconfigured_provider_fails_naming_it() -> None:
    with pytest.raises(ProviderAuthError, match="zerobounce"):
        build_finder_chain(settings(hunter_api_key="h", finder_chain="hunter,zerobounce"))


def test_asking_for_an_unknown_provider_lists_the_choices() -> None:
    with pytest.raises(ProviderAuthError, match="hunter"):
        build_finder_chain(settings(finder_chain="nope"))


def test_single_verifier_and_resolver_builders_follow_settings() -> None:
    s = settings(myemailverifier_api_key="m", enrichley_api_key="e", catch_all_resolver="enrichley")
    assert build_verifier(s).name == "myemailverifier"
    assert build_resolver(s).name == "enrichley"


def test_secrets_do_not_appear_in_the_settings_repr() -> None:
    assert "super-secret" not in repr(settings(hunter_api_key="super-secret"))
