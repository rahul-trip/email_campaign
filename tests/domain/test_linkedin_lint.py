"""What a LinkedIn connection note and message may and may not say."""

from __future__ import annotations

from outbound.domain.linkedin import NOTE_MAX_CHARS, lint_linkedin

MESSAGE = " ".join(["word"] * 70)


def test_a_short_note_and_a_message_of_the_right_length_pass() -> None:
    assert lint_linkedin("Saw your Leeds contract. We forecast grid load.", MESSAGE) == []


def test_a_note_over_the_limit_is_flagged_with_its_length() -> None:
    (issue,) = lint_linkedin("x " * 150, MESSAGE)
    assert str(NOTE_MAX_CHARS) in issue


def test_a_message_that_is_too_short_or_too_long_is_flagged() -> None:
    assert any("words" in i for i in lint_linkedin("Hello", "too short"))
    assert any("words" in i for i in lint_linkedin("Hello", " ".join(["word"] * 140)))


def test_links_addresses_placeholders_and_template_wording_are_flagged() -> None:
    assert lint_linkedin("See https://acme.com", MESSAGE)
    assert lint_linkedin("Write to jane@acme.com", MESSAGE)
    assert lint_linkedin("Hi [Name]", MESSAGE)
    assert lint_linkedin("Hello", MESSAGE + " I am reaching out about this email")
    assert lint_linkedin("", MESSAGE)  # an empty note
