"""Backup vendors: the next verifier or resolver takes over when one fails."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from outbound.config import Settings
from outbound.pipeline import real_providers
from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.ports import (
    ResolutionResult,
    ResolutionStatus,
    ResolutionTicket,
    VerificationResult,
    VerificationStatus,
)
from outbound.stages.email.fallback import ResolverChain, VerifierChain

EMAIL = "ada@example.com"


class Verifier:
    def __init__(self, name: str, *, fails: bool = False) -> None:
        self.name, self.fails, self.calls = name, fails, 0

    def verify(self, email: str) -> VerificationResult:
        self.calls += 1
        if self.fails:
            raise ProviderAuthError(self.name, "401")
        return VerificationResult(email=email, status=VerificationStatus.VALID, provider=self.name)


class Resolver:
    def __init__(self, name: str, *, fails: bool = False, real_time: bool = False) -> None:
        self.name, self.fails, self.real_time = name, fails, real_time
        self.polled: list[str] = []

    def submit(self, email: str) -> ResolutionTicket:
        if self.fails:
            raise ProviderAuthError(self.name, "401")
        result = self._result(email) if self.real_time else None
        return ResolutionTicket(
            ref=f"{self.name}-1", email=email, provider=self.name, result=result
        )

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        self.polled.append(ticket.ref)
        return self._result(ticket.email)

    def _result(self, email: str) -> ResolutionResult:
        return ResolutionResult(email=email, status=ResolutionStatus.VALID, provider=self.name)


def test_a_refused_verifier_hands_over_to_the_next() -> None:
    first, second = Verifier("myemailverifier", fails=True), Verifier("orbisearch")
    result = VerifierChain([first, second]).verify(EMAIL)
    assert result.provider == "orbisearch"
    assert (first.calls, second.calls) == (1, 1)


def test_the_first_verifier_that_answers_is_the_only_one_asked() -> None:
    first, second = Verifier("myemailverifier"), Verifier("orbisearch")
    assert VerifierChain([first, second]).verify(EMAIL).provider == "myemailverifier"
    assert second.calls == 0


def test_when_every_verifier_fails_the_error_names_each() -> None:
    chain = VerifierChain([Verifier("a", fails=True), Verifier("b", fails=True)])
    with pytest.raises(ProviderError) as caught:
        chain.verify(EMAIL)
    assert "a: 401" in str(caught.value) and "b: 401" in str(caught.value)


def test_a_lone_vendor_failing_raises_its_own_error() -> None:
    with pytest.raises(ProviderAuthError):
        VerifierChain([Verifier("a", fails=True)]).verify(EMAIL)


def test_a_refused_resolver_hands_over_and_its_ticket_is_polled_where_it_was_taken() -> None:
    scrubby = Resolver("scrubby", fails=True)
    enrichley = Resolver("enrichley", real_time=True)
    chain = ResolverChain([scrubby, enrichley])
    ticket = chain.submit(EMAIL)
    assert ticket.provider == "enrichley" and ticket.result is not None
    chain.poll(ticket)
    assert enrichley.polled == ["enrichley-1"] and scrubby.polled == []


def test_an_old_ticket_saved_under_the_verifier_goes_to_the_first_resolver() -> None:
    scrubby, enrichley = Resolver("scrubby"), Resolver("enrichley")
    chain = ResolverChain([scrubby, enrichley])
    chain.poll(ResolutionTicket(ref="old", email=EMAIL, provider="myemailverifier"))
    assert scrubby.polled == ["old"]


def _settings(**keys: str) -> Settings:
    update: dict[str, object] = {
        f"{name}_api_key": SecretStr(value) for name, value in keys.items()
    }
    update |= {
        "tavily_api_key": SecretStr("t" * 12),
        "llm_api_key": SecretStr("l" * 12),
        "finder_chain": ["hunter"],
        "verifier": "myemailverifier",
        "catch_all_resolver": "scrubby",
    }
    return Settings().model_copy(update=update)


def test_every_vendor_with_a_key_is_a_backup_the_dedicated_verifiers_first() -> None:
    keys = {
        name: name[0] * 12
        for name in ("hunter", "myemailverifier", "orbisearch", "scrubby", "enrichley")
    }
    providers = real_providers(_settings(**keys))
    assert providers.verifier.name == "myemailverifier"
    assert [v.name for v in providers.backup_verifiers] == ["orbisearch", "hunter"]
    assert providers.resolver is not None and providers.resolver.name == "scrubby"
    assert [r.name for r in providers.backup_resolvers] == ["enrichley"]


def test_without_the_chosen_resolver_the_other_one_is_used() -> None:
    providers = real_providers(
        _settings(hunter="h" * 12, myemailverifier="m" * 12, enrichley="e" * 12)
    )
    assert providers.resolver is not None and providers.resolver.name == "enrichley"
    assert providers.backup_resolvers == []
