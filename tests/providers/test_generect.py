from __future__ import annotations

import json

import httpx
import pytest

from outbound.providers.adapters.generect import GenerectFinder
from outbound.providers.errors import BudgetExceeded
from tests.contract._shared import SECRET
from tests.contract.finder_contract import DOMAIN, PERSON, EmailFinderContract
from tests.providers.helpers import Handler, always, fixture, mock_client, respond


class TestGenerectFinder(EmailFinderContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> GenerectFinder:
        return GenerectFinder(api_key, client=mock_client(handler))

    def found(self) -> httpx.Response:
        return respond("generect/finder_found.json")

    def not_found(self) -> httpx.Response:
        return respond("generect/finder_not_found.json")

    def test_the_request_and_the_token_prefix(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.found()

        self.build(handler).find(PERSON, DOMAIN)
        request = seen[0]
        assert request.url.path == "/api/v1/email/find/"
        assert request.headers["authorization"] == f"Token {SECRET}"
        assert json.loads(request.content) == {
            "first_name": "Jane", "last_name": "Doe", "domain": DOMAIN,
        }  # fmt: skip

    def test_a_charge_of_zero_means_nothing_was_billed(self) -> None:
        body = fixture("generect/finder_found.json")
        body["meta"]["amount_charged"] = 0
        result = self.build(always(httpx.Response(200, json=body))).find(PERSON, DOMAIN)
        assert result.email == "jane.doe@acme.com" and result.billed is False

    @pytest.mark.parametrize("said", ["risky", "invalid", "unknown"])
    def test_only_a_valid_result_is_taken(self, said: str) -> None:
        body = fixture("generect/finder_found.json")
        body["data"]["result"] = said
        result = self.build(always(httpx.Response(200, json=body))).find(PERSON, DOMAIN)
        assert result.email is None and result.billed is False

    def test_no_credit_is_out_of_credit(self) -> None:
        with pytest.raises(BudgetExceeded):
            self.build(always(httpx.Response(402, json={"detail": "Payment required"}))).find(
                PERSON, DOMAIN
            )
