from __future__ import annotations

import json

import httpx
import pytest

from outbound.providers.adapters.anymailfinder import AnymailFinder
from outbound.providers.errors import BudgetExceeded, ProviderAuthError
from outbound.providers.ports import PersonQuery
from tests.contract._shared import SECRET
from tests.contract.finder_contract import DOMAIN, PERSON, EmailFinderContract
from tests.providers.helpers import Handler, always, fixture, mock_client, respond


class TestAnymailFinder(EmailFinderContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> AnymailFinder:
        return AnymailFinder(api_key, client=mock_client(handler))

    def found(self) -> httpx.Response:
        return respond("anymailfinder/finder_found.json")

    def not_found(self) -> httpx.Response:
        return respond("anymailfinder/finder_not_found.json")

    def auth_failed(self) -> httpx.Response:
        return respond("anymailfinder/error_bad_key.json", status=401)

    def test_the_request_names_the_person_and_domain_and_the_key_has_no_bearer(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.found()

        self.build(handler).find(PERSON, DOMAIN)
        request = seen[0]
        assert request.url.path == "/v5.1/find-email/person"
        assert request.headers["authorization"] == SECRET  # as it is: no "Bearer"
        assert json.loads(request.content) == {
            "domain": DOMAIN, "first_name": "Jane", "last_name": "Doe",
        }  # fmt: skip

    def test_a_linkedin_profile_is_sent_when_known(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.found()

        person = PersonQuery(
            first_name="Jane", last_name="Doe", linkedin_url="https://www.linkedin.com/in/jane"
        )
        self.build(handler).find(person, DOMAIN)
        assert json.loads(seen[0].content)["linkedin_url"] == "https://www.linkedin.com/in/jane"

    @pytest.mark.parametrize("status", ["not_found", "blacklisted", "risky", ""])
    def test_only_a_valid_address_is_taken(self, status: str) -> None:
        body = {**fixture("anymailfinder/finder_found.json"), "email_status": status}
        result = self.build(always(httpx.Response(200, json=body))).find(PERSON, DOMAIN)
        assert result.email is None and result.billed is False and result.raw_status == status

    def test_a_valid_address_found_again_within_30_days_is_free(self) -> None:
        body = {**fixture("anymailfinder/finder_found.json"), "credits_charged": 0}
        result = self.build(always(httpx.Response(200, json=body))).find(PERSON, DOMAIN)
        assert result.email == "jane.doe@acme.com" and result.billed is False

    def test_no_credits_is_out_of_credit_not_a_miss(self) -> None:
        response = respond("anymailfinder/error_no_credits.json", status=402)
        with pytest.raises(BudgetExceeded):
            self.build(always(response)).find(PERSON, DOMAIN)

    def test_a_bad_key_is_an_auth_failure(self) -> None:
        with pytest.raises(ProviderAuthError):
            self.build(always(self.auth_failed())).find(PERSON, DOMAIN)
