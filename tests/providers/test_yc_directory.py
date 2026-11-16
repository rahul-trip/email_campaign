from __future__ import annotations

import json

import httpx

from outbound.domain.brief import Brief
from outbound.providers.adapters.yc_directory import YcDirectory
from outbound.providers.ports import SourceQuery
from outbound.services.discovery import source_query
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


def _company(name: str, text: str, places: str, regions: list[str]) -> dict[str, object]:
    return {
        "name": name, "status": "Active", "one_liner": text, "all_locations": places,
        "regions": regions, "website": f"https://{name.lower()}.com", "batch": "Winter 2023",
    }  # fmt: skip


def custom(*companies: dict[str, object]) -> YcDirectory:
    return YcDirectory(client=mock_client(lambda _: httpx.Response(200, json=list(companies))))


def test_keywords_match_whole_words_not_parts_of_words() -> None:
    found = custom(
        _company("Mailco", "We maintain email lists", "Austin, TX, USA", ["United States"]),
        _company("Gridai", "AI for grid operators", "Austin, TX, USA", ["United States"]),
    ).find(SourceQuery(keywords=("ai",)), limit=5)
    assert [m.name for m in found] == ["Gridai"]


def test_regions_match_whole_places_and_their_common_names() -> None:
    directory = custom(
        _company("Londonco", "grid", "London, ENG, United Kingdom", ["United Kingdom", "Europe"]),
        _company("Moscowco", "grid", "Moscow, Russia", ["Russia"]),
        _company("Ohioco", "grid", "Columbus, OH, USA", ["United States of America"]),
    )

    def where(region: str) -> list[str]:
        return [
            m.name
            for m in directory.find(SourceQuery(keywords=("grid",), regions=(region,)), limit=5)
        ]

    assert where("UK") == ["Londonco"]
    assert where("US") == ["Ohioco"]
    assert where("Europe") == ["Londonco"]


# Entries cut unchanged from the real directory (yc-oss), with a decoy that only says "power".
REAL = json.loads((FIXTURES / "yc/real_energy.json").read_text())
# The brief that found nothing in production: no keywords, a one-word summary, whole segments.
PRODUCTION = Brief.from_json(
    {
        "summary": "Energy start-ups",
        "company_type": "startup",
        "segments": ["VPP/DER platforms", "BESS integrators", "Grid analytics start-ups"],
    }
)


def real() -> YcDirectory:
    return custom(*REAL)


def test_the_brief_that_found_nothing_in_production_finds_energy_start_ups() -> None:
    found = real().find(source_query(PRODUCTION), limit=10)
    names = [m.name for m in found]
    assert {"Squid", "Condor Energy", "Nira Energy", "Raptor Maps"} <= set(names)
    assert "Benchling" not in names  # says "the power of" in prose only: one word is not enough


def test_among_equal_matches_the_newest_batch_comes_first() -> None:
    found = real().find(SourceQuery(keywords=("energy",)), limit=10)
    batches = [m.evidence.split(":")[0] for m in found]
    assert batches.index("Y Combinator Fall 2026") < batches.index("Y Combinator Winter 2026")
    assert batches.index("Y Combinator Winter 2026") < batches.index("Y Combinator Summer 2016")


def test_a_second_search_with_the_first_ones_websites_excluded_brings_other_companies() -> None:
    directory = real()
    first = directory.find(source_query(PRODUCTION), limit=3)
    known = [m.domain for m in first if m.domain]
    second = directory.find(source_query(PRODUCTION, known=known), limit=3)
    assert len(first) == len(second) == 3
    assert not {m.domain for m in first} & {m.domain for m in second}
    # The exclusion comes before the limit: once all are known, nothing is left to return.
    every = directory.find(source_query(PRODUCTION), limit=100)
    known = [m.domain for m in every if m.domain]
    assert directory.find(source_query(PRODUCTION, known=known), limit=3) == []


def test_what_the_directory_knows_reaches_screening() -> None:
    [squid] = [m for m in real().find(source_query(PRODUCTION), limit=10) if m.name == "Squid"]
    assert "Y Combinator Winter 2026" in squid.evidence
    assert " people" in squid.evidence and "stage" in squid.evidence
    assert squid.evidence.count(";") >= 2  # size, stage, place, tags: one line the model reads


def test_words_match_by_stem_and_a_label_hit_is_enough() -> None:
    labelled = _company("Wattly", "We help teams", "Leeds, UK", ["United Kingdom"])
    labelled["tags"] = ["Utility", "Energy"]
    prose = _company("Gridly", "Forecasting grids for the electricity utilities", "x", [])
    found = custom(labelled, prose).find(SourceQuery(keywords=("utilities", "grid")), limit=5)
    assert {m.name for m in found} == {"Wattly", "Gridly"}  # utilities = utility; grids = grid
    assert found[0].name == "Wattly"  # a label counts more than prose
