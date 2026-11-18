from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.orbisearch import OrbiSearchResolver, OrbiSearchVerifier
from outbound.providers.errors import ProviderAuthError
from outbound.providers.ports import ResolutionStatus, VerificationStatus
from tests.contract._shared import SECRET
from tests.contract.verifier_contract import EmailVerifierContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestOrbiSearchVerifier(EmailVerifierContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> OrbiSearchVerifier:
        return OrbiSearchVerifier(api_key, client=mock_client(handler))

    def make_responses(self) -> dict[VerificationStatus, httpx.Response]:
        return {
            VerificationStatus.VALID: respond("orbisearch/verify_safe.json"),
            VerificationStatus.CATCH_ALL: respond("orbisearch/verify_risky.json"),
            VerificationStatus.INVALID: respond("orbisearch/verify_invalid.json"),
            VerificationStatus.UNKNOWN: respond("orbisearch/verify_unknown.json"),
        }

    def test_raw_status_keeps_the_substatus(self) -> None:
        result = self.build(always(respond("orbisearch/verify_risky.json"))).verify("a@b.com")
        assert result.raw_status == "risky/catch_all"

    def test_key_is_sent_in_the_x_api_key_header(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("orbisearch/verify_safe.json")

        self.build(handler).verify("a@b.com")
        assert seen[0].headers["x-api-key"] == SECRET
        assert seen[0].url.params["email"] == "a@b.com"

    def test_insufficient_credits_is_reported_as_a_credential_problem(self) -> None:
        with pytest.raises(ProviderAuthError):
            self.build(always(httpx.Response(403))).verify("a@b.com")


class TestOrbiSearchResolver:
    """The same check, asked of an address a verifier called catch-all: answered with the call."""

    def build(self, answer: dict[str, object]) -> OrbiSearchResolver:
        return OrbiSearchResolver(
            SECRET, client=mock_client(always(httpx.Response(200, json=answer)))
        )

    def test_safe_is_valid_and_invalid_is_invalid_with_the_answer_on_the_ticket(self) -> None:
        for vendor, ours in (
            ("safe", ResolutionStatus.VALID),
            ("invalid", ResolutionStatus.INVALID),
        ):
            ticket = self.build({"status": vendor}).submit("jane@acme.com")
            assert ticket.result is not None and ticket.result.status is ours
            assert ticket.provider == "orbisearch" and ticket.result.billed

    def test_risky_and_unknown_are_unresolved_so_the_chain_asks_the_next(self) -> None:
        for vendor in ("risky", "unknown", "something-new"):
            ticket = self.build({"status": vendor, "substatus": "catch_all"}).submit("a@b.co")
            assert ticket.result is not None
            assert ticket.result.status is ResolutionStatus.UNRESOLVED

    def test_it_is_marked_real_time_and_never_leaves_a_ticket_pending(self) -> None:
        resolver = self.build({"status": "safe"})
        assert resolver.realtime is True
        ticket = resolver.submit("a@b.co")
        assert resolver.poll(ticket) == ticket.result
