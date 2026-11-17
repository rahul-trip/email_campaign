"""Several keys for one vendor: a random one per call, and a bad one is skipped."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from outbound.config import Settings
from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError, RateLimited
from outbound.providers.keypool import KeyPool, ResolverKeyPool
from outbound.providers.ports import ResolutionResult, ResolutionStatus, ResolutionTicket
from outbound.providers.registry import build_resolver, build_search, configured_verifiers


class Member:
    name = "tavily"

    def __init__(self, key: str, error: ProviderError | None = None) -> None:
        self.key, self.error, self.calls = key, error, 0

    def search(self, query: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return f"{self.key}:{query}"


def in_order(order: list[int]) -> None:
    """No shuffle: the keys are tried 1, 2, 3."""


def reversed_order(order: list[int]) -> None:
    order.reverse()


def test_each_call_goes_to_the_key_the_shuffle_puts_first() -> None:
    a, b = Member("a"), Member("b")
    assert KeyPool([a, b], shuffle=in_order).search("q") == "a:q"
    assert KeyPool([a, b], shuffle=reversed_order).search("q") == "b:q"


def test_the_default_shuffle_spreads_calls_over_every_key() -> None:
    members = [Member(k) for k in "abc"]
    pool = KeyPool(members)
    for _ in range(200):
        pool.search("q")
    assert all(m.calls > 20 for m in members)


@pytest.mark.parametrize(
    "error",
    [ProviderAuthError("tavily", "401"), RateLimited("tavily"), BudgetExceeded("tavily", "432")],
)
def test_a_refused_limited_or_empty_key_is_skipped(error: ProviderError) -> None:
    bad, good = Member("bad", error), Member("good")
    assert KeyPool([bad, good], shuffle=in_order).search("q") == "good:q"
    assert bad.calls == 1


def test_an_outage_is_not_retried_with_other_keys() -> None:
    down, good = Member("down", ProviderError("tavily", "503")), Member("good")
    with pytest.raises(ProviderError, match="503"):
        KeyPool([down, good], shuffle=in_order).search("q")
    assert good.calls == 0


def test_when_every_key_is_refused_the_refusal_is_raised() -> None:
    pool = KeyPool([Member(k, ProviderAuthError("tavily", "401")) for k in "ab"])
    with pytest.raises(ProviderAuthError):
        pool.search("q")


def test_the_pool_has_the_vendor_name() -> None:
    assert KeyPool([Member("a"), Member("b")]).name == "tavily"


class Queue:
    name = "scrubby"

    def __init__(self, key: str) -> None:
        self.key = key
        self.polled: list[str] = []

    def submit(self, email: str) -> ResolutionTicket:
        return ResolutionTicket(ref=f"{self.key}-id", email=email, provider=self.name)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        self.polled.append(ticket.ref)
        return ResolutionResult(
            email=ticket.email, status=ResolutionStatus.VALID, provider=self.name
        )


def test_a_queued_check_is_polled_with_the_key_that_queued_it() -> None:
    first, second = Queue("a"), Queue("b")
    pool = ResolverKeyPool([first, second], shuffle=reversed_order)
    ticket = pool.submit("ada@example.com")
    assert ticket.ref == "k2:b-id"
    pool.poll(ticket)
    assert second.polled == ["b-id"] and first.polled == []


def test_a_ticket_from_before_the_pool_goes_to_the_first_key() -> None:
    first, second = Queue("a"), Queue("b")
    ResolverKeyPool([first, second]).poll(
        ResolutionTicket(ref="plain-id", email="ada@example.com", provider="scrubby")
    )
    assert first.polled == ["plain-id"]


def _settings(**pools: list[str]) -> Settings:
    update: dict[str, object] = {
        "vendor_key_pools": {code: [SecretStr(k) for k in keys] for code, keys in pools.items()}
    }
    for code, keys in pools.items():
        update[f"{code}_api_key"] = SecretStr(keys[0])
    return Settings().model_copy(update=update)


def test_the_registry_pools_a_vendor_with_several_keys_and_not_one_with_one() -> None:
    settings = _settings(tavily=["t" * 12, "u" * 12], orbisearch=["o" * 12])
    assert isinstance(build_search(settings), KeyPool)
    assert not isinstance(configured_verifiers(settings)["orbisearch"], KeyPool)


def test_a_resolver_with_several_keys_gets_the_resolver_pool() -> None:
    settings = _settings(scrubby=["s" * 12, "r" * 12]).model_copy(
        update={"catch_all_resolver": "scrubby"}
    )
    assert isinstance(build_resolver(settings), ResolverKeyPool)
