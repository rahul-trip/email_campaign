"""The ideal-customer brief: parsed tolerantly from a model's or an operator's JSON."""

from __future__ import annotations

from outbound.domain.brief import Brief, CompanyType, Criterion


def test_a_full_brief_round_trips() -> None:
    data = {
        "summary": "European energy-forecasting start-ups that sell to grid operators.",
        "company_type": "startup",
        "keywords": ["energy forecasting", "grid analytics"],
        "segments": ["B2B SaaS start-ups"],
        "regions": ["Germany", "GB"],
        "size_range": "10-200 employees",
        "founded_after": 2015,
        "funding_stages": ["seed", "series a"],
        "industry_codes": ["62012", "35110"],
        "must_haves": [{"text": "sells software", "weight": 3}],
        "disqualifiers": ["competitor: sells forecasting software"],
        "buying_signals": ["recent funding"],
        "source_hints": ["accelerator cohorts"],
        "seed_companies": ["amperon.co"],
    }
    brief = Brief.from_json(data)
    assert brief.company_type is CompanyType.STARTUP
    assert brief.must_haves == (Criterion("sells software", 3),)
    assert Brief.from_json(brief.to_json()) == brief


def test_plain_strings_become_criteria_with_weight_one() -> None:
    brief = Brief.from_json({"must_haves": ["B2B", "  "], "company_type": "nonsense"})
    assert brief.must_haves == (Criterion("B2B", 1),)
    assert brief.company_type is CompanyType.ANY


def test_weights_are_clamped_and_lists_cleaned() -> None:
    brief = Brief.from_json(
        {
            "must_haves": [{"text": "a", "weight": 99}, {"text": "b", "weight": "x"}],
            "keywords": ["Grid", "grid ", 7, "", "x" * 500],
            "industry_codes": ["62012", "not a code", "123"],
            "founded_after": 1700,
        }
    )
    assert [c.weight for c in brief.must_haves] == [3, 1]
    assert brief.keywords == ("Grid", "x" * 120)  # duplicates, non-strings and blanks dropped
    assert brief.industry_codes == ("62012",)
    assert brief.founded_after is None


def test_garbage_gives_an_empty_brief() -> None:
    assert Brief.from_json(None).is_empty
    assert Brief.from_json({"keywords": "not a list"}).is_empty
    assert not Brief.from_json({"summary": "x"}).is_empty
