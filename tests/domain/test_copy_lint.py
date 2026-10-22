from __future__ import annotations

import pytest

from outbound.domain.copy_lint import LintReport, LintRules, count_words, lint
from outbound.domain.editing import edit_distance
from tests.stages.fakes import GOOD_BODY as CORE

FOOTER = "Quantra Ltd, 1 High St, Leeds. Reply unsubscribe and we will stop."
GREETING, SIGNATURE = "Hi Jane,\n\n", "\n\nSam Lee\nCPO, Quantra"


def issues(report: LintReport) -> set[str]:
    return {i.rule for i in report.issues}


def check(
    core: str = CORE,
    subject: str = "solar forecast error",
    step: int = 0,
    footer: str | None = FOOTER,
    with_footer: bool = True,
    rules: LintRules | None = None,
) -> LintReport:
    """Lint the writer's paragraphs, in the whole email code would assemble around them."""
    body = f"{GREETING}{core}{SIGNATURE}"
    if footer is not None and with_footer:
        body = f"{body}\n\n--\n{footer}"
    return lint(
        body=body, subject=subject, step=step, footer=footer, core=core, rules=rules or LintRules()
    )


def test_a_good_first_email_has_no_issues() -> None:
    report = check()
    assert issues(report) == set(), report.feedback()
    assert not report.flagged
    assert 120 <= report.word_count <= 200


def test_greeting_signature_and_footer_are_not_counted_towards_the_length() -> None:
    long_footer = "word " * 200
    report = check(footer=long_footer.strip())
    assert "length" not in issues(report)
    assert report.word_count == count_words(CORE)


@pytest.mark.parametrize(
    ("words", "step", "bad"),
    [
        (30, 0, True),  # the old 3-liner is now too short
        (119, 0, True),
        (120, 0, False),
        (200, 0, False),
        (201, 0, True),
        (30, 1, False),
        (60, 1, True),
        (10, 1, True),
    ],
)
def test_length_limits_differ_for_a_first_email_and_a_follow_up(
    words: int, step: int, bad: bool
) -> None:
    core = ("word " * (words - 3)).strip() + " Can we talk?"
    assert ("length" in issues(check(core, step=step))) is bad


def test_the_first_email_length_follows_the_workspace_setting() -> None:
    short = ("word " * 77).strip() + " Can we talk?"  # 80 words
    assert "length" in issues(check(short))
    assert "length" not in issues(check(short, rules=LintRules.with_length(60, 100)))


@pytest.mark.parametrize(
    ("subject", "bad"),
    [
        ("solar forecast error", False),
        ("quick question", False),
        ("leeds grid contract and forecasting", False),
        ("Solar forecast error", True),
        ("forecasts", True),
        ("seven words are far too many here today", True),
        ("", True),
    ],
)
def test_the_subject_is_two_to_six_lower_case_words(subject: str, bad: bool) -> None:
    assert ("subject" in issues(check(subject=subject))) is bad


def test_a_dense_email_fails_the_reading_level() -> None:
    dense = (
        "Notwithstanding considerable methodological heterogeneity, organisational "
        "decarbonisation trajectories necessitate probabilistic generation forecasting "
        "infrastructure; consequently, interconnected stakeholders increasingly prioritise "
        "operationalised optimisation capabilities across heterogeneous portfolios, whereas "
        "institutional counterparties characteristically require interoperability. "
        "Would a conversation be worthwhile?"
    )
    assert "reading_level" in issues(check(dense))


@pytest.mark.parametrize(("questions", "bad"), [(0, True), (1, False), (2, False), (3, True)])
def test_there_is_one_or_two_questions(questions: int, bad: bool) -> None:
    core = CORE.replace("?", ".") + " Is it?" * questions
    assert ("call_to_action" in issues(check(core))) is bad


def test_a_first_email_must_not_contain_a_link_but_a_follow_up_may() -> None:
    linked = CORE.replace("in days", "in days (see https://quantra.example/demo)")
    assert "links" in issues(check(linked))
    assert "links" in issues(check(CORE.replace("dispatch tools", "www.quantra.example")))
    assert "links" not in issues(check(linked, step=1))


@pytest.mark.parametrize(
    "phrase",
    [
        "I hope this email finds you well",
        "Let's touch base",
        "leverage",
        "We see strong potential here",
        "Potential synergies include these",
        "It integrates seamlessly",
        "to empower your team",
        "I'm reaching out about this",
        "your impressive growth",
    ],
)
def test_phrases_that_read_as_machine_written_are_flagged(phrase: str) -> None:
    report = check(CORE.replace("We work on exactly that.", f"{phrase}."))
    assert "banned_phrase" in issues(report)


@pytest.mark.parametrize(
    "bullet", ["• Forecasting", "- Forecasting", "* Forecasting", "1. Forecasting", "2) Dispatch"]
)
def test_a_list_is_flagged_but_a_hyphenated_word_is_not(bullet: str) -> None:
    assert "bullets" in issues(check(CORE + f"\n\n{bullet}\n{bullet}"))
    assert "bullets" not in issues(check(CORE.replace("day-ahead", "day-ahead and well-known")))


def test_more_than_one_em_dash_is_flagged() -> None:
    one = CORE.replace("That usually", "That — usually")
    two = one.replace("Nothing there", "Nothing — there")
    assert "dashes" not in issues(check(one))
    assert "dashes" in issues(check(two))


def test_the_old_three_liner_template_now_fails_on_length() -> None:
    old = (
        "I saw that Acme opened a new Leeds office to run its solar fleet. Forecast errors on a "
        "fleet that size turn straight into trading losses. We cut forecast error by about a "
        "quarter for a UK trader. Would a short call next week make sense?"
    )
    assert issues(check(old)) == {"length"}


def test_a_missing_footer_is_flagged_but_none_expected_is_fine() -> None:
    assert "footer" in issues(check(with_footer=False))
    assert "footer" not in issues(check(footer=None))


def test_without_a_core_the_whole_body_minus_the_footer_is_measured() -> None:
    body = f"{GREETING}{CORE}{SIGNATURE}\n\n--\n{FOOTER}"
    report = lint(body=body, subject="solar forecast error", step=0, footer=FOOTER)
    assert report.word_count == count_words(f"{GREETING}{CORE}{SIGNATURE}")


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
    small = edit_distance(CORE, CORE.replace("Leeds", "Manchester"))
    big = edit_distance(CORE, "Completely different text about something else entirely.")
    assert 0 < small < 0.1
    assert big > 0.7


def test_distance_is_bounded() -> None:
    assert 0.0 <= edit_distance("abc", "xyz") <= 1.0
    assert edit_distance("", "") == 0.0


def test_an_email_address_in_the_body_is_flagged() -> None:
    assert "address_in_body" in issues(check(CORE + " Write to sam@quantra.example."))
    assert "address_in_body" not in issues(check())
