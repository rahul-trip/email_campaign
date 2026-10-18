from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.myemailverifier import MyEmailVerifierVerifier
from outbound.providers.ports import VerificationStatus
from tests.contract._shared import SECRET
from tests.contract.verifier_contract import EmailVerifierContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestMyEmailVerifier(EmailVerifierContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> MyEmailVerifierVerifier:
        return MyEmailVerifierVerifier(api_key, client=mock_client(handler))

    def make_responses(self) -> dict[VerificationStatus, httpx.Response]:
        return {
            VerificationStatus.VALID: respond("myemailverifier/validate_valid.json"),
            VerificationStatus.CATCH_ALL: respond("myemailverifier/validate_catch_all.json"),
            VerificationStatus.INVALID: respond("myemailverifier/validate_invalid.json"),
            VerificationStatus.UNKNOWN: respond("myemailverifier/validate_greylisted.json"),
        }

    @pytest.mark.parametrize(
        ("fixture_name", "expected"),
        [
            ("myemailverifier/validate_disposable.json", VerificationStatus.INVALID),
            ("myemailverifier/validate_unrecognised.json", VerificationStatus.UNKNOWN),
        ],
    )
    def test_disposable_is_unusable_and_unrecognised_is_never_valid(
        self, fixture_name: str, expected: VerificationStatus
    ) -> None:
        assert self.build(always(respond(fixture_name))).verify("a@b.com").status is expected

    def test_a_valid_status_with_the_catch_all_flag_is_not_valid(self) -> None:
        body = {"Status": "Valid", "catch_all": "true"}
        result = self.build(always(httpx.Response(200, json=body))).verify("a@b.com")
        assert result.status is VerificationStatus.CATCH_ALL

    def test_raw_status_keeps_the_vendor_spelling(self) -> None:
        result = self.build(always(respond("myemailverifier/validate_unrecognised.json"))).verify(
            "a@b.com"
        )
        assert result.raw_status == "Something New"

    def test_request_uses_the_documented_parameter_names(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("myemailverifier/validate_valid.json")

        self.build(handler).verify("a@b.com")
        assert seen[0].url.path.endswith("/validate_single.php")
        assert seen[0].url.params["apikey"] == SECRET
        assert seen[0].url.params["email"] == "a@b.com"
