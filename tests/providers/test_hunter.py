from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.hunter import HunterFinder, HunterVerifier
from outbound.providers.errors import ProviderError
from outbound.providers.ports import PersonQuery, VerificationStatus
from tests.contract._shared import SECRET
from tests.contract.finder_contract import EmailFinderContract
from tests.contract.verifier_contract import EmailVerifierContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestHunterFinder(EmailFinderContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> HunterFinder:
        return HunterFinder(api_key, client=mock_client(handler))

    def found(self) -> httpx.Response:
        return respond("hunter/finder_found.json")

    def not_found(self) -> httpx.Response:
        return respond("hunter/finder_not_found.json")

    def test_confidence_is_the_hunter_score_scaled_to_0_1(self) -> None:
        result = self.build(always(self.found())).find(
            PersonQuery(first_name="J", last_name="D"), "acme.com"
        )
        assert result.confidence == pytest.approx(0.97)
        assert result.raw_status == "valid"

    def test_key_travels_in_a_header_not_the_url(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.found()

        self.build(handler).find(PersonQuery(first_name="J", last_name="D"), "acme.com")
        assert SECRET not in str(seen[0].url)
        assert seen[0].headers["x-api-key"] == SECRET

    def test_a_person_who_opted_out_is_reported_not_raised(self) -> None:
        result = self.build(
            always(httpx.Response(451, json={"errors": [{"id": "claimed_email"}]}))
        ).find(PersonQuery(first_name="J", last_name="D"), "acme.com")
        assert result.email is None
        assert result.raw_status == "claimed_email"
        assert result.billed is False


class TestHunterVerifier(EmailVerifierContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> HunterVerifier:
        return HunterVerifier(api_key, client=mock_client(handler))

    def make_responses(self) -> dict[VerificationStatus, httpx.Response]:
        return {
            VerificationStatus.VALID: respond("hunter/verifier_valid.json"),
            VerificationStatus.CATCH_ALL: respond("hunter/verifier_accept_all.json"),
            VerificationStatus.INVALID: respond("hunter/verifier_invalid.json"),
            VerificationStatus.UNKNOWN: respond("hunter/verifier_unknown.json"),
        }

    @pytest.mark.parametrize(
        ("fixture_name", "expected"),
        [
            ("hunter/verifier_webmail.json", VerificationStatus.UNKNOWN),
            ("hunter/verifier_disposable.json", VerificationStatus.INVALID),
        ],
    )
    def test_webmail_is_unproven_and_disposable_is_unusable(
        self, fixture_name: str, expected: VerificationStatus
    ) -> None:
        assert self.build(always(respond(fixture_name))).verify("jane@acme.com").status is expected

    def test_a_202_is_polled_until_hunter_finishes(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(202) if len(calls) < 2 else respond("hunter/verifier_valid.json")

        assert self.build(handler).verify("jane@acme.com").status is VerificationStatus.VALID
        assert len(calls) == 2

    def test_an_unrecognised_status_is_never_treated_as_valid(self) -> None:
        response = httpx.Response(200, json={"data": {"status": "brand_new"}})
        assert self.build(always(response)).verify("a@b.com").status is VerificationStatus.UNKNOWN

    def test_a_person_who_opted_out_is_invalid_and_free(self) -> None:
        result = self.build(always(httpx.Response(451))).verify("jane@acme.com")
        assert result.status is VerificationStatus.INVALID
        assert result.billed is False

    def test_other_client_errors_still_raise(self) -> None:
        with pytest.raises(ProviderError):
            self.build(
                always(httpx.Response(400, json={"errors": [{"id": "invalid_email"}]}))
            ).verify("x")
