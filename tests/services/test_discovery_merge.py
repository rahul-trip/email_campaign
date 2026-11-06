"""Merging what the sources found: one entry per company, never two companies as one."""

from __future__ import annotations

from outbound.domain.discovery import name_key
from outbound.providers.ports import CompanyMention
from outbound.services.discovery import merge


def mention(name: str, domain: str | None = None, source: str = "exa") -> CompanyMention:
    return CompanyMention(name=name, domain=domain, source=source)


def test_two_companies_with_the_same_name_but_different_websites_stay_two() -> None:
    found = merge([mention("Home", "alpha.com"), mention("Home", "beta.io")])
    assert sorted(f.domain or "" for f in found) == ["alpha.com", "beta.io"]
    assert len({f.key for f in found}) == 2


def test_a_name_without_a_website_joins_the_one_company_of_that_name() -> None:
    found = merge(
        [
            mention("Gridcast", source="articles"),
            mention("Gridcast", "gridcast.io", source="yc_directory"),
            mention("Gridcast Ltd", source="companies_house"),
        ]
    )
    [one] = found
    assert one.domain == "gridcast.io"
    assert one.sources == ["articles", "yc_directory", "companies_house"]


def test_the_same_website_is_the_same_company_whatever_its_name() -> None:
    [one] = merge([mention("Gridcast", "gridcast.io"), mention("Gridcast | Home", "gridcast.io")])
    assert one.sources == ["exa"]


def test_accented_and_non_latin_names_are_kept() -> None:
    assert name_key("Société Générale") == "societe generale"
    [kept] = merge([mention("株式会社", "kabushiki.jp")])
    assert kept.key and kept.domain == "kabushiki.jp"
    assert merge([mention("株式会社")]) == []  # no name to compare and no website
