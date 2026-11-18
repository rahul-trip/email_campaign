from __future__ import annotations

import json

import httpx
import pytest

from outbound.providers.adapters.prospeo import ProspeoFinder
from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError
from outbound.providers.ports import FinderResult
from tests.contract._shared import SECRET
from tests.contract.finder_contract import DOMAIN, PERSON, EmailFinderContract
from tests.providers.helpers import Handler, always, fixture, mock_client, respond


class TestProspeoFinder(EmailFinderContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> ProspeoFinder:
        return ProspeoFinder(api_key, client=mock_client(handler))

    def found(self) -> httpx.Response:
        return respond("prospeo/finder_found.json")

    def not_found(self) -> httpx.Response:
        return respond("prospeo/error_no_match.json", status=400)  # how Prospeo says "no match"

    def auth_failed(self) -> httpx.Response:
        return httpx.Response(401, json={"error": True})

    def find(self, response: httpx.Response) -> FinderResult:
        return self.build(always(response)).find(PERSON, DOMAIN)

    def test_the_request_asks_for_a_verified_address_with_the_key_in_x_key(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.found()

        self.build(handler).find(PERSON, DOMAIN)
        request = seen[0]
        assert request.url.path == "/enrich-person" and request.headers["x-key"] == SECRET
        assert json.loads(request.content) == {
            "only_verified_email": True,
            "data": {"first_name": "Jane", "last_name": "Doe", "company_website": DOMAIN},
        }

    def test_no_match_is_a_free_miss_though_the_vendor_answers_400(self) -> None:
        result = self.find(respond("prospeo/error_no_match.json", status=400))
        assert result.email is None and result.billed is False

    def test_no_match_in_a_200_body_is_a_miss_too(self) -> None:
        assert (
            self.find(httpx.Response(200, json={"error": True, "error_code": "NO_MATCH"})).email
            is None
        )

    def test_no_credits_is_out_of_credit_and_a_bad_key_is_an_auth_failure(self) -> None:
        with pytest.raises(BudgetExceeded):
            self.find(respond("prospeo/error_insufficient_credits.json", status=400))
        with pytest.raises(ProviderAuthError):
            self.find(respond("prospeo/error_invalid_key.json", status=400))

    def test_any_other_400_is_a_real_error_not_a_miss(self) -> None:
        body = {"error": True, "error_code": "INVALID_DATAPOINTS"}
        with pytest.raises(ProviderError):
            self.find(httpx.Response(400, json=body))

    def test_a_masked_or_unverified_address_is_not_taken(self) -> None:
        assert self.find(respond("prospeo/finder_masked.json")).email is None
        body = fixture("prospeo/finder_found.json")
        body["person"]["email"]["status"] = "UNVERIFIED"
        assert self.find(httpx.Response(200, json=body)).email is None

    def test_a_found_address_is_lowercase_verified_and_billed(self) -> None:
        result = self.find(self.found())
        assert (result.email, result.raw_status, result.billed) == (
            "jane.doe@acme.com", "verified", True,
        )  # fmt: skip
