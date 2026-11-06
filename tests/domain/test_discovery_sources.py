"""Choosing where to look for companies, and how a company found twice is recognised."""

from __future__ import annotations

import pytest

from outbound.domain.brief import Brief
from outbound.domain.discovery import (
    ARTICLES,
    CH,
    EXA,
    YC,
    SourceYield,
    article_queries,
    name_key,
    plan_sources,
    share,
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


ALL = {YC, CH, EXA, ARTICLES}
UK_SME = Brief.from_json(
    {"company_type": "sme", "regions": ["United Kingdom"], "industry_codes": ["35110"]}
)


def test_the_uk_register_is_searched_only_for_a_uk_brief_with_industry_codes() -> None:
    assert plan_sources(UK_SME, available=ALL) == [CH, EXA, ARTICLES]
    no_codes = Brief.from_json({"company_type": "sme", "regions": ["UK"]})
    assert CH not in plan_sources(no_codes, available=ALL)
    abroad = Brief.from_json({"regions": ["Germany"], "industry_codes": ["35110"]})
    assert CH not in plan_sources(abroad, available=ALL)
    for place in ("GB", "England", "Scotland", "the UK"):
        brief = Brief.from_json({"regions": [place], "industry_codes": ["35110"]})
        assert CH in plan_sources(brief, available=ALL), place


def test_lookalike_search_is_used_whenever_its_key_is_set() -> None:
    assert plan_sources(STARTUPS, available=ALL) == [YC, EXA, ARTICLES]
    assert EXA not in plan_sources(STARTUPS, available={YC, ARTICLES})


def test_sources_whose_leads_qualify_more_often_are_asked_first() -> None:
    yields = {YC: SourceYield(found=40, qualified=2), ARTICLES: SourceYield(found=40, qualified=12)}
    assert plan_sources(STARTUPS, available=ALL, yields=yields) == [ARTICLES, EXA, YC]


def test_too_little_history_does_not_change_the_order() -> None:
    yields = {YC: SourceYield(found=3, qualified=0), ARTICLES: SourceYield(found=4, qualified=4)}
    assert plan_sources(STARTUPS, available=ALL, yields=yields) == [YC, EXA, ARTICLES]


def test_a_good_source_gets_a_bigger_share_and_a_poor_one_a_smaller_but_never_none() -> None:
    yields = {
        YC: SourceYield(found=50, qualified=1),  # 2%
        ARTICLES: SourceYield(found=50, qualified=39),  # 78%
        EXA: SourceYield(found=50, qualified=20),  # 40%, the average
    }
    assert share(ARTICLES, yields) == pytest.approx(1.95)
    assert share(YC, yields) == 0.5  # 0.05 of the average, but never less than half
    assert share(EXA, yields) == pytest.approx(1.0)
    assert share(CH, yields) == 1.0  # nothing known yet
    assert share(YC, {}) == 1.0
