from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.millionverifier import MillionVerifierVerifier
from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError
from outbound.providers.ports import VerificationStatus
from tests.contract._shared import SECRET
from tests.contract.verifier_contract import EmailVerifierContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestMillionVerifier(EmailVerifierContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> MillionVerifierVerifier:
        return MillionVerifierVerifier(api_key, client=mock_client(handler))

    def make_responses(self) -> dict[VerificationStatus, httpx.Response]:
        return {
            VerificationStatus.VALID: respond("millionverifier/verify_ok.json"),
            VerificationStatus.CATCH_ALL: respond("millionverifier/verify_catch_all.json"),
            VerificationStatus.INVALID: respond("millionverifier/verify_invalid.json"),
            VerificationStatus.UNKNOWN: respond("millionverifier/verify_unknown.json"),
        }

    def test_a_disposable_address_is_unusable_and_an_unrecognised_answer_is_never_valid(
        self,
    ) -> None:
        disposable = self.build(always(respond("millionverifier/verify_disposable.json")))
        assert disposable.verify("a@b.com").status is VerificationStatus.INVALID
        new = self.build(always(httpx.Response(200, json={"result": "something_new"})))
        assert new.verify("a@b.com").status is VerificationStatus.UNKNOWN

    @pytest.mark.parametrize(
        ("fixture_name", "charged"),
        [
            ("millionverifier/verify_ok.json", True),
            ("millionverifier/verify_invalid.json", True),
            ("millionverifier/verify_disposable.json", True),
            ("millionverifier/verify_catch_all.json", False),
            ("millionverifier/verify_unknown.json", False),
        ],
    )
    def test_only_a_settled_answer_is_charged(self, fixture_name: str, charged: bool) -> None:
        assert self.build(always(respond(fixture_name))).verify("a@b.com").billed is charged

    def test_an_error_is_read_from_the_body_not_the_http_status(self) -> None:
        bad_key = self.build(always(respond("millionverifier/error_bad_key.json")))
        with pytest.raises(ProviderAuthError):
            bad_key.verify("a@b.com")
        no_credits = self.build(always(respond("millionverifier/error_no_credits.json")))
        with pytest.raises(BudgetExceeded):
            no_credits.verify("a@b.com")
        other = self.build(always(httpx.Response(200, json={"result": "error", "error": "Oops"})))
        with pytest.raises(ProviderError) as info:
            other.verify("a@b.com")
        assert not isinstance(info.value, ProviderAuthError | BudgetExceeded)
        assert SECRET not in str(info.value)

    def test_the_request_follows_the_docs(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("millionverifier/verify_ok.json")

        self.build(handler).verify("a@b.com")
        assert seen[0].url.host == "api.millionverifier.com"
        assert seen[0].url.path == "/api/v3/"
        assert seen[0].url.params["api"] == SECRET
        assert seen[0].url.params["email"] == "a@b.com"
        assert seen[0].url.params["timeout"] == "20"
