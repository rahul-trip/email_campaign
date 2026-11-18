from __future__ import annotations

import json

import httpx
import pytest

from outbound.providers.adapters.icypeas import IcypeasFinder
from outbound.providers.errors import BudgetExceeded, ProviderError
from tests.contract._shared import SECRET
from tests.contract.finder_contract import DOMAIN, PERSON, EmailFinderContract
from tests.providers.helpers import Handler, fixture, mock_client, respond


def finder(handler: Handler, *, polls: int = 8, key: str = SECRET) -> IcypeasFinder:
    return IcypeasFinder(key, client=mock_client(handler), sleep=lambda _: None, polls=polls)


def sequence(*reads: dict[str, object]) -> tuple[Handler, list[httpx.Request]]:
    """Answers the search with an id, then each read in turn (the last one repeats)."""
    seen: list[httpx.Request] = []
    pending = list(reads)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/email-search"):
            return respond("icypeas/search_started.json")
        return httpx.Response(200, json=pending.pop(0) if len(pending) > 1 else pending[0])

    return handler, seen


class TestIcypeasFinder(EmailFinderContract):
    # The contract answers both of the finder's calls with one body, so the fixtures hold both.
    def build(self, handler: Handler, api_key: str = SECRET) -> IcypeasFinder:
        return finder(handler, key=api_key)

    def found(self) -> httpx.Response:
        return respond("icypeas/both_found.json")

    def not_found(self) -> httpx.Response:
        return respond("icypeas/both_not_found.json")

    def test_the_search_then_the_read_with_the_key_as_it_is(self) -> None:
        handler, seen = sequence(fixture("icypeas/read_found.json"))
        result = finder(handler).find(PERSON, DOMAIN)
        assert result.email == "jane.doe@acme.com" and result.billed is True
        assert [r.url.path for r in seen] == ["/api/email-search", "/api/bulk-single-searchs/read"]
        assert json.loads(seen[0].content) == {
            "firstname": "Jane", "lastname": "Doe", "domainOrCompany": DOMAIN,
        }  # fmt: skip
        assert json.loads(seen[1].content) == {"id": "kMnquYkBTs8kZM9ND26h"}
        assert seen[0].headers["authorization"] == SECRET  # no "Bearer"

    def test_it_waits_while_the_search_is_still_running(self) -> None:
        waits: list[float] = []
        handler, _ = sequence(
            fixture("icypeas/read_pending.json"),
            fixture("icypeas/read_pending.json"),
            fixture("icypeas/read_found.json"),
        )
        adapter = IcypeasFinder(
            SECRET, client=mock_client(handler), sleep=waits.append, polls=8, every=3.0
        )
        assert adapter.find(PERSON, DOMAIN).email == "jane.doe@acme.com"
        assert waits == [3.0, 3.0, 3.0]  # three reads, three seconds apart: the 30 a minute limit

    def test_a_search_that_never_finishes_is_an_error_not_nothing_found(self) -> None:
        handler, _ = sequence(fixture("icypeas/read_pending.json"))
        with pytest.raises(ProviderError, match="had not finished"):
            finder(handler, polls=3).find(PERSON, DOMAIN)

    def test_no_credit_is_out_of_credit(self) -> None:
        body = {"success": True, "items": [{"status": "INSUFFICIENT_FUNDS"}]}
        handler, _ = sequence(body)
        with pytest.raises(BudgetExceeded):
            finder(handler).find(PERSON, DOMAIN)

    def test_a_refused_search_body_is_an_error(self) -> None:
        refused = {"success": False, "validationErrors": [{"field": "domainOrCompany"}]}
        with pytest.raises(ProviderError, match="not accepted"):
            finder(lambda request: httpx.Response(200, json=refused)).find(PERSON, DOMAIN)

    def test_the_most_certain_address_wins_and_undeliverable_is_never_taken(self) -> None:
        emails = [
            {"email": "j@acme.com", "certainty": "undeliverable"},
            {"email": "jane@acme.com", "certainty": "probable"},
            {"email": "Jane.Doe@acme.com", "certainty": "ultra_sure"},
        ]
        handler, _ = sequence({"items": [{"status": "FOUND", "results": {"emails": emails}}]})
        result = finder(handler).find(PERSON, DOMAIN)
        assert (result.email, result.confidence) == ("jane.doe@acme.com", 0.99)
        only_bad = [{"email": "j@acme.com", "certainty": "undeliverable"}]
        handler, _ = sequence({"items": [{"status": "FOUND", "results": {"emails": only_bad}}]})
        assert finder(handler).find(PERSON, DOMAIN).email is None
