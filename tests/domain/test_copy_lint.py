from __future__ import annotations

import pytest

from outbound.domain.copy_lint import LintReport, LintRules, count_words, lint
from outbound.domain.editing import edit_distance

FOOTER = "Quantra Ltd, 1 High St, Leeds. Reply unsubscribe and we will stop."
GOOD_BODY = (
    "Hi Jane,\n\n"
    "I read about your new Leeds office and the solar sites you are adding. "
    "Forecasts that miss by a few percent cost you money on the trading desk. "
    "We cut that error by about a quarter for a UK trader, using the data you already hold. "
    "It plugs into your current dispatch tools in days, not months.\n\n"
    "Would a short call next week make sense?\n\n"
    "Sam Lee\nCPO, Quantra"
)


def full(body: str = GOOD_BODY, footer: str | None = FOOTER) -> str:
    return body if footer is None else f"{body}\n\n--\n{footer}"


def issues(report: LintReport) -> set[str]:
    return {i.rule for i in report.issues}


def check(
    body: str = GOOD_BODY,
    subject: str = "solar forecast error",
    step: int = 0,
    footer: str | None = FOOTER,
    with_footer: bool = True,
) -> LintReport:
    text = full(body, footer) if with_footer else body
    return lint(body=text, subject=subject, step=step, footer=footer)


def test_a_good_first_email_has_no_issues() -> None:
    report = check()
    assert issues(report) == set(), report.feedback()
    assert not report.flagged
    assert 50 <= report.word_count <= 85


def test_the_footer_is_not_counted_towards_the_length() -> None:
    long_footer = "word " * 200
    report = check(footer=long_footer.strip())
    assert "length" not in issues(report)


@pytest.mark.parametrize(
    ("body", "step", "bad"),
    [
        ("Hi Jane,\n\nShort one. Can we talk?", 0, True),
        ("word " * 90 + "Can we talk?", 0, True),
        ("word " * 30 + "Can we talk?", 1, False),
        ("word " * 60 + "Can we talk?", 1, True),
        ("word " * 10 + "Can we talk?", 1, True),
    ],
)
def test_length_limits_differ_for_a_first_email_and_a_follow_up(
    body: str, step: int, bad: bool
) -> None:
    assert ("length" in issues(check(body, step=step))) is bad


@pytest.mark.parametrize(
    ("subject", "bad"),
    [
        ("solar forecast error", False),
        ("quick question", False),
        ("Solar forecast error", True),
        ("forecasts", True),
        ("six words are far too many here", True),
        ("", True),
    ],
)
def test_the_subject_is_two_to_five_lower_case_words(subject: str, bad: bool) -> None:
    assert ("subject" in issues(check(subject=subject))) is bad


def test_a_dense_email_fails_the_reading_level() -> None:
    dense = (
        "Notwithstanding considerable methodological heterogeneity, organisational "
        "decarbonisation trajectories necessitate probabilistic generation forecasting "
        "infrastructure; consequently, interconnected stakeholders increasingly prioritise "
        "operationalised optimisation capabilities across heterogeneous portfolios. "
        "Would a conversation be worthwhile?"
    )
    assert "reading_level" in issues(check(dense))


@pytest.mark.parametrize(("questions", "bad"), [(0, True), (1, False), (2, True)])
def test_there_is_exactly_one_question(questions: int, bad: bool) -> None:
    body = GOOD_BODY.replace(
        "Would a short call next week make sense?", "Please reply." + " Is it?" * questions
    )
    if questions == 0:
        body = GOOD_BODY.replace("?", ".")
    assert ("call_to_action" in issues(check(body))) is bad


def test_a_first_email_must_not_contain_a_link_but_a_follow_up_may() -> None:
    linked = GOOD_BODY.replace("in days", "in days (see https://quantra.example/demo)")
    assert "links" in issues(check(linked))
    assert "links" in issues(check(GOOD_BODY.replace("dispatch tools", "www.quantra.example")))
    assert "links" not in issues(check(linked, step=1))


@pytest.mark.parametrize(
    "phrase", ["I hope this email finds you well", "Let's touch base", "leverage"]
)
def test_banned_phrases_are_flagged(phrase: str) -> None:
    report = check(GOOD_BODY.replace("Hi Jane,", f"Hi Jane, {phrase}."))
    assert "banned_phrase" in issues(report)


def test_a_missing_footer_is_flagged_but_none_expected_is_fine() -> None:
    assert "footer" in issues(check(with_footer=False))
    assert "footer" not in issues(check(footer=None))


def test_custom_rules_change_the_limits() -> None:
    rules = LintRules(first_touch_words=(5, 20), banned_phrases=())
    report = lint(body="Hi Jane, can we talk?", subject="hello there", step=0, rules=rules)
    assert issues(report) == set()


def test_the_report_serialises_for_storage_and_explains_itself() -> None:
    report = check(subject="Bad Subject")
    data = report.to_json()
    assert data["flagged"] is True
    assert data["issues"][0]["rule"] == "subject"
    assert "all lower case" in report.feedback()


def test_words_are_counted_without_punctuation() -> None:
    assert count_words("Hi Jane, it's 3 pm - ok?") == 6


# ------------------------------------------------------------------ edit distance


def test_an_unchanged_email_has_distance_zero_even_if_whitespace_differs() -> None:
    assert edit_distance("Hi Jane,\n\nHello.", "Hi Jane,   Hello. ") == 0.0


def test_a_small_edit_is_a_small_distance_and_a_rewrite_is_large() -> None:
    small = edit_distance(GOOD_BODY, GOOD_BODY.replace("Leeds", "Manchester"))
    big = edit_distance(GOOD_BODY, "Completely different text about something else entirely.")
    assert 0 < small < 0.1
    assert big > 0.7


def test_distance_is_bounded() -> None:
    assert 0.0 <= edit_distance("abc", "xyz") <= 1.0
    assert edit_distance("", "") == 0.0
