from __future__ import annotations

import json

import httpx

from outbound.providers.adapters.yc_directory import YcDirectory
from outbound.providers.ports import SourceQuery
from tests.providers.helpers import FIXTURES, mock_client

ALL = json.loads((FIXTURES / "yc/all.json").read_text())


def directory(seen: list[httpx.Request] | None = None) -> YcDirectory:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=ALL)

    return YcDirectory(client=mock_client(handler))


def test_active_companies_matching_the_keywords_come_first() -> None:
    found = directory().find(SourceQuery(keywords=("energy forecasting", "grid")), limit=5)
    assert [m.name for m in found] == ["Gridcast", "Voltwise"]  # Old Grid Co is inactive
    first = found[0]
    assert first.domain == "gridcast.io"
    assert first.source == "yc_directory"
    assert first.source_url == "https://www.ycombinator.com/companies/gridcast"
    assert "European grid operators" in first.description
    assert first.country == "Germany" and first.size == "18" and first.founded == 2022
    assert "Winter 2022" in first.evidence


def test_regions_and_founding_year_narrow_the_list() -> None:
    query = SourceQuery(keywords=("energy",), regions=("Germany",))
    assert [m.name for m in directory().find(query, limit=5)] == ["Gridcast"]
    query = SourceQuery(keywords=("energy",), founded_after=2020)
    assert [m.name for m in directory().find(query, limit=5)] == ["Gridcast"]


def test_no_keyword_match_means_nothing_found_and_the_list_is_fetched_once() -> None:
    seen: list[httpx.Request] = []
    yc = directory(seen)
    assert yc.find(SourceQuery(keywords=("quantum chemistry",)), limit=5) == []
    yc.find(SourceQuery(keywords=("energy",)), limit=5)
    assert len(seen) == 1  # the whole directory is one download, kept for a day
    assert yc.find(SourceQuery(), limit=5) == []  # no keywords: no basis to choose
