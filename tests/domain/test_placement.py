"""Who works at the company: the rules, on real results from a live run."""

from __future__ import annotations

import pytest

from outbound.domain.placement import Placement, place_by_rules, without_name


def place(
    name: str, headline: str, employer: str, company: str, domain: str, snippet: str = ""
) -> Placement:
    return place_by_rules(
        name=name,
        headline=headline,
        employer=employer,
        snippet=snippet,
        company=company,
        domain=domain,
    ).placement


@pytest.mark.parametrize(
    ("name", "headline", "employer", "company", "domain", "expected"),
    [
        # the profile names exactly this company
        (
            "Ben Dyer",
            "Founder/CTO, HyperProbe (YC S26)",
            "",
            "HyperProbe",
            "hyperprobe.co",
            "works_here",
        ),
        ("Jane Doe", "CTO", "Acme Energy", "Acme Energy Ltd", "acme.co.uk", "works_here"),
        ("Sam Lee", "CTO at Golf", "", "Golf", "golf.dev", "works_here"),
        # a person who only shares the company's name
        ("Kristen Coval", "Amazon Web Services (AWS)", "", "Coval", "coval.dev", "not_here"),
        (
            "Patrick Coval",
            "East Rochester, New York, United States",
            "",
            "Coval",
            "coval.dev",
            "not_here",
        ),
        ("Aiir Consulting", "", "", "Aiir", "useaiir.com", "not_here"),
        ("Rei Orikata", "", "", "Orikata Bio", "orikata.ai", "not_here"),
        # a different employer
        ("Dan Roth", "CTO", "G&W Electric", "Volue", "volue.com", "not_here"),
        # a longer company name is not this company: the model decides
        ("Jared Solomon", "Co-Founder & CEO, Five Iron Golf", "", "Golf", "golf.dev", "unsure"),
        ("Isak Bergset", "Head of Sale, Volue Power Grid", "", "Volue", "volue.com", "unsure"),
        # nothing to go on
        ("Sam Lee", "Chief Technology Officer", "", "Volue", "volue.com", "unsure"),
    ],
)
def test_rules_place_the_clear_cases_and_leave_the_rest(
    name: str, headline: str, employer: str, company: str, domain: str, expected: str
) -> None:
    assert place(name, headline, employer, company, domain) is Placement(expected)


def test_a_person_the_companys_own_site_names_works_here() -> None:
    placed = place_by_rules(
        name="Kaoru Orikata",
        headline="",
        employer="",
        snippet="",
        company="Orikata Bio",
        domain="orikata.ai",
        site_text="Our team: Kaoru Orikata, founder, and others.",
    )
    assert placed.placement is Placement.WORKS_HERE


def test_a_surname_is_not_read_as_the_company_being_mentioned() -> None:
    assert "coval" not in without_name("Kristen Coval at Amazon", "Kristen Coval").split()


def test_a_snippet_that_names_the_company_keeps_a_namesake_unsure() -> None:
    placed = place_by_rules(
        name="Pierre Coval",
        headline="COO",
        employer="",
        snippet="Pierre leads operations at Coval since 2020",
        company="Coval",
        domain="coval.dev",
    )
    assert placed.placement is Placement.UNSURE


def test_one_shared_word_in_the_employer_is_another_company() -> None:
    placed = place(
        name="Jithin James", headline="Data Science", employer="Gapblue Software Labs Pvt Ltd",
        company="Vibrant Labs", domain="vibrantlabs.com",
    )  # fmt: skip
    assert placed is Placement.NOT_HERE
