from __future__ import annotations

import json

import httpx
import pytest

from outbound.providers.adapters.tavily import TavilySearch
from outbound.providers.errors import BudgetExceeded
from tests.contract._shared import SECRET
from tests.contract.search_contract import SearchProviderContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestTavilySearch(SearchProviderContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> TavilySearch:
        return TavilySearch(api_key, client=mock_client(handler))

    def search_response(self) -> httpx.Response:
        return respond("tavily/search.json")

    def extract_response(self) -> httpx.Response:
        return respond("tavily/extract.json")

    def test_search_maps_vendor_fields(self) -> None:
        hit = self.build(always(self.search_response())).search("q")[0]
        assert (hit.url, hit.title, hit.snippet, hit.score) == (
            "https://acme.com/team",
            "Acme leadership team",
            "Jane Doe, CTO.",
            0.91,
        )

    def test_failed_and_empty_pages_are_left_out(self) -> None:
        pages = self.build(always(self.extract_response())).extract(["a", "b", "c"])
        assert [page.url for page in pages] == ["https://acme.com/about"]

    def test_key_is_a_bearer_token_and_max_results_is_capped(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.search_response()

        self.build(handler).search("q", max_results=500)
        assert seen[0].headers["authorization"] == f"Bearer {SECRET}"
        assert json.loads(seen[0].read())["max_results"] == 20

    def test_extract_is_split_into_requests_of_at_most_20_urls(self) -> None:
        sizes: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sizes.append(len(json.loads(request.read())["urls"]))
            return self.extract_response()

        self.build(handler).extract([f"https://acme.com/{i}" for i in range(45)])
        assert sizes == [20, 20, 5]

    @pytest.mark.parametrize("status", [432, 433])
    def test_vendor_plan_limits_are_reported_as_budget_exceeded(self, status: int) -> None:
        with pytest.raises(BudgetExceeded):
            self.build(always(httpx.Response(status))).search("q")
