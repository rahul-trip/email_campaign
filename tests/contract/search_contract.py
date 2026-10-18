"""Contract for the SearchProvider port."""

from __future__ import annotations

import httpx

from outbound.providers.ports import PageText, SearchHit, SearchProvider
from tests.contract._shared import AdapterContract
from tests.providers.helpers import always


class SearchProviderContract(AdapterContract):
    def search_response(self) -> httpx.Response:
        raise NotImplementedError

    def extract_response(self) -> httpx.Response:
        raise NotImplementedError

    def ok_response(self) -> httpx.Response:
        return self.search_response()

    def call(self, adapter: SearchProvider) -> list[SearchHit]:
        return adapter.search("acme leadership")

    def test_search_returns_hits_and_skips_results_without_a_url(self) -> None:
        hits = self.call(self.build(always(self.search_response())))
        assert hits
        assert all(isinstance(hit, SearchHit) and hit.url for hit in hits)

    def test_extract_returns_only_pages_that_have_text(self) -> None:
        pages = self.build(always(self.extract_response())).extract(["https://acme.com/about"])
        assert pages
        assert all(isinstance(page, PageText) and page.text for page in pages)

    def test_extract_of_nothing_makes_no_request(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return self.extract_response()

        assert self.build(handler).extract([]) == []
        assert calls == []
