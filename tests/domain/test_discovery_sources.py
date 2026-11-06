"""Choosing where to look for companies, and how a company found twice is recognised."""

from __future__ import annotations

from outbound.domain.brief import Brief
from outbound.domain.discovery import (
    ARTICLES,
    YC,
    article_queries,
    name_key,
    plan_sources,
)
from outbound.domain.enums import CandidateVerdict

STARTUPS = Brief.from_json(
    {
        "company_type": "startup",
        "keywords": ["energy forecasting", "grid analytics"],
        "segments": ["start-ups"],
        "regions": ["Europe", "US"],
        "source_hints": ["funding round-ups"],
    }
)


def test_a_company_is_recognised_whatever_its_legal_suffix_or_case() -> None:
    assert name_key("Acme Energy Ltd.") == name_key("ACME energy") == "acme energy"
    assert name_key("Grid & Co GmbH") == name_key("grid and co")
    assert name_key("  ") == ""


def test_start_ups_are_looked_for_in_the_yc_directory_before_articles() -> None:
    assert plan_sources(STARTUPS, available={YC, ARTICLES}) == [YC, ARTICLES]


def test_a_brief_for_established_firms_skips_start_up_directories() -> None:
    sme = Brief.from_json({"company_type": "sme", "keywords": ["utilities"]})
    assert plan_sources(sme, available={YC, ARTICLES}) == [ARTICLES]
    assert plan_sources(Brief(), available={YC, ARTICLES}) == [YC, ARTICLES]  # "any"
    assert plan_sources(STARTUPS, available={YC}) == [YC]  # no web search set up


def test_article_searches_combine_what_they_do_who_they_are_and_where() -> None:
    queries = article_queries(STARTUPS, used=[], limit=3)
    assert queries[0] == "energy forecasting start-ups in Europe"
    assert queries[1] == "energy forecasting start-ups in US"
    assert queries[2] == "grid analytics start-ups in Europe"
    later = article_queries(STARTUPS, used=queries, limit=10)
    assert not set(later) & set(queries)
    assert "funding round-ups energy forecasting start-ups" in later  # a kind of list page


def test_a_brief_with_nothing_to_search_gives_no_queries() -> None:
    assert article_queries(Brief(), used=[], limit=3) == []


def test_verdicts_are_the_closed_set_stored_with_each_candidate() -> None:
    assert {v.value for v in CandidateVerdict} == {
        "accepted",
        "rejected",
        "unresolved",
        "already_lead",
        "over_limit",
    }
