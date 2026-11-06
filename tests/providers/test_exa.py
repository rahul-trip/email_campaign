"""Exa: neural search for companies, and companies like an example customer."""

from __future__ import annotations

import json

import httpx
import pytest

from outbound.providers.adapters.exa import ExaSearch
from outbound.providers.errors import ProviderError
from outbound.providers.ports import SourceQuery
from tests.providers.helpers import mock_client, respond


def exa(seen: list[httpx.Request], status: int = 200) -> ExaSearch:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "invalid key"})
        name = "find_similar" if request.url.path == "/findSimilar" else "search"
        return respond(f"exa/{name}.json")

    return ExaSearch("exa-key-123", client=mock_client(handler))


def test_companies_are_searched_for_by_what_the_brief_says() -> None:
    seen: list[httpx.Request] = []
    found = exa(seen).find(SourceQuery(text="Utilities that forecast load"), limit=10)
    [request] = seen
    body = json.loads(request.content)
    assert request.url.path == "/search" and request.headers["x-api-key"] == "exa-key-123"
    assert body["query"] == "Utilities that forecast load"
    assert body["category"] == "company" and body["numResults"] == 10
    assert [(m.name, m.domain) for m in found] == [
        ("Gridcast", "gridcast.io"),
        ("Voltwise", "voltwise.com"),
    ]
    assert found[0].source == "exa" and found[0].source_url == "https://www.gridcast.io/"
    assert "European grid operators" in found[0].description


def test_without_a_summary_the_brief_words_make_the_search() -> None:
    seen: list[httpx.Request] = []
    exa(seen).find(SourceQuery(keywords=("grid forecasting",), regions=("UK",)), limit=5)
    assert json.loads(seen[0].content)["query"] == "grid forecasting companies in UK"


def test_example_customers_bring_lookalikes_once_each() -> None:
    seen: list[httpx.Request] = []
    query = SourceQuery(text="grid", seed_domains=("Octopus Energy", "kraken.tech"))
    found = exa(seen).find(query, limit=10)
    similar = [json.loads(r.content) for r in seen if r.url.path == "/findSimilar"]
    assert [s["url"] for s in similar] == ["https://kraken.tech"]  # a name is not a website
    assert [m.domain for m in found] == ["gridcast.io", "voltwise.com", "amperon.co"]
    amperon = found[-1]
    assert amperon.name == "Amperon" and "like kraken.tech" in amperon.evidence


def test_a_refused_key_is_a_provider_error() -> None:
    with pytest.raises(ProviderError):
        exa([], status=401).find(SourceQuery(text="grid"), limit=5)
