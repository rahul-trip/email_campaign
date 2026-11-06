"""Qualifying a researched company against the brief, criterion by criterion."""

from __future__ import annotations

from outbound.domain.brief import Brief
from outbound.domain.qualification import Check, Verdict, checks, qualify

BRIEF = Brief.from_json(
    {
        "must_haves": [
            {"text": "operates on the power grid", "weight": 3},
            {"text": "has a data team", "weight": 1},
        ],
        "buying_signals": ["recent funding", "hiring data scientists"],
        "disqualifiers": ["sells forecasting software"],
    }
)


def said(verdict: str, evidence: str = "the site says so") -> dict[str, str]:
    return {"verdict": verdict, "evidence": evidence, "source": "https://acme.com"}


def test_every_criterion_has_a_short_id_the_model_answers_by() -> None:
    assert checks(BRIEF) == [
        Check("M1", "must_have", "operates on the power grid", 3),
        Check("M2", "must_have", "has a data team", 1),
        Check("S1", "signal", "recent funding", 1),
        Check("S2", "signal", "hiring data scientists", 1),
        Check("D1", "disqualifier", "sells forecasting software", 1),
    ]


def test_every_must_have_met_with_a_signal_scores_high() -> None:
    result = qualify(BRIEF, {"M1": said("met"), "M2": said("met"), "S1": said("met")})
    assert result.score == 80 and not result.ruled_out
    assert result.reason == "Meets 2 of 2 must-haves; signs they may buy now: recent funding"


def test_must_haves_count_by_weight_and_an_unknown_counts_half() -> None:
    result = qualify(BRIEF, {"M1": said("met"), "M2": said("unknown")})
    assert result.score == 61  # 70 x (3 + 0.5) / 4
    assert "not known: has a data team" in result.reason


def test_a_missing_must_have_says_which() -> None:
    result = qualify(BRIEF, {"M1": said("not_met"), "M2": said("met")})
    assert result.score == 18  # 70 x 1 / 4
    assert result.reason.startswith("Meets 1 of 2 must-haves; missing: operates on the power grid")


def test_a_disqualifier_that_is_met_rules_the_company_out_whatever_else() -> None:
    result = qualify(
        BRIEF,
        {"M1": said("met"), "M2": said("met"), "D1": said("met", "they sell Forecaster")},
    )
    assert result.score == 0 and result.ruled_out
    assert result.reason == "Ruled out: sells forecasting software (they sell Forecaster)"


def test_an_unanswered_or_garbled_criterion_is_unknown() -> None:
    result = qualify(BRIEF, {"M1": {"verdict": "maybe?"}, "X9": said("met")})
    assert {i.check.id: i.verdict for i in result.items}["M1"] is Verdict.UNKNOWN
    assert [i.check.id for i in result.items] == ["M1", "M2", "S1", "S2", "D1"]


def test_signals_add_at_most_thirty() -> None:
    many = Brief.from_json({"buying_signals": ["a", "b", "c", "d"]})
    result = qualify(many, {f"S{n}": said("met") for n in range(1, 5)})
    assert result.score == 80  # 50 with no must-haves set, plus 30


def test_the_breakdown_is_stored_as_plain_json() -> None:
    data = qualify(BRIEF, {"M1": said("met")}).to_json()
    assert data["score"] == qualify(BRIEF, {"M1": said("met")}).score
    first = data["criteria"][0]
    assert first == {
        "id": "M1",
        "kind": "must_have",
        "criterion": "operates on the power grid",
        "weight": 3,
        "verdict": "met",
        "evidence": "the site says so",
        "source": "https://acme.com",
    }
