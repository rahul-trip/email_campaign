from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.zerobounce import ZeroBounceFinder, ZeroBounceVerifier
from outbound.providers.errors import ProviderError
from outbound.providers.ports import PersonQuery, VerificationStatus
from tests.contract._shared import SECRET
from tests.contract.finder_contract import EmailFinderContract
from tests.contract.verifier_contract import EmailVerifierContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestZeroBounceFinder(EmailFinderContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> ZeroBounceFinder:
        return ZeroBounceFinder(api_key, client=mock_client(handler))

    def found(self) -> httpx.Response:
        return respond("zerobounce/finder_found.json")

    def not_found(self) -> httpx.Response:
        return respond("zerobounce/finder_unknown.json")

    def auth_failed(self) -> httpx.Response:
        return respond("zerobounce/error_invalid_key.json")  # HTTP 200 with an error body

    def test_confidence_label_becomes_a_number(self) -> None:
        result = self.build(always(self.found())).find(
            PersonQuery(first_name="J", last_name="D"), "acme.com"
        )
        assert result.confidence == pytest.approx(0.9)
        assert result.raw_status == "HIGH"

    def test_failure_reason_is_kept_when_nothing_is_found(self) -> None:
        result = self.build(always(self.not_found())).find(
            PersonQuery(first_name="J", last_name="D"), "acme.com"
        )
        assert result.raw_status == "NO_DATA_FOR_THIS_DOMAIN"
        assert result.confidence is None

    def test_a_non_credit_error_body_is_a_plain_provider_error(self) -> None:
        response = httpx.Response(200, json={"error": "Domain is required"})
        with pytest.raises(ProviderError) as info:
            self.build(always(response)).find(PersonQuery(first_name="J", last_name="D"), "")
        assert not info.value.retryable


class TestZeroBounceVerifier(EmailVerifierContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> ZeroBounceVerifier:
        return ZeroBounceVerifier(api_key, client=mock_client(handler))

    def make_responses(self) -> dict[VerificationStatus, httpx.Response]:
        return {
            VerificationStatus.VALID: respond("zerobounce/validate_valid.json"),
            VerificationStatus.CATCH_ALL: respond("zerobounce/validate_catch_all.json"),
            VerificationStatus.INVALID: respond("zerobounce/validate_invalid.json"),
            VerificationStatus.UNKNOWN: respond("zerobounce/validate_unknown.json"),
        }

    def auth_failed(self) -> httpx.Response:
        return respond("zerobounce/error_invalid_key.json")

    @pytest.mark.parametrize(
        "fixture_name",
        ["zerobounce/validate_spamtrap.json", "zerobounce/validate_do_not_mail.json"],
    )
    def test_traps_and_do_not_mail_are_never_safe(self, fixture_name: str) -> None:
        result = self.build(always(respond(fixture_name))).verify("jane@acme.com")
        assert result.status is VerificationStatus.INVALID

    def test_an_unknown_answer_is_free_and_the_others_are_billed(self) -> None:
        unknown = self.build(always(respond("zerobounce/validate_unknown.json"))).verify("a@b.com")
        valid = self.build(always(respond("zerobounce/validate_valid.json"))).verify("a@b.com")
        assert unknown.billed is False
        assert valid.billed is True

    def test_sub_status_is_not_needed_and_raw_status_is_the_vendor_label(self) -> None:
        result = self.build(always(respond("zerobounce/validate_catch_all.json"))).verify("a@b.com")
        assert result.raw_status == "catch-all"
