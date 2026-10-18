from __future__ import annotations

import pytest

from outbound.stages.email.patterns import (
    build_address,
    infer_pattern,
    local_part,
    matches_person,
)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("{first}.{last}", "jane.doe"),
        ("{f}{last}", "jdoe"),
        ("{first}", "jane"),
        ("{first}{l}", "janed"),
        ("{last}.{first}", "doe.jane"),
    ],
)
def test_patterns_build_a_mailbox_name(pattern: str, expected: str) -> None:
    assert local_part(pattern, "Jane", "Doe") == expected


def test_accents_and_punctuation_are_folded() -> None:
    assert build_address("{first}.{last}", "Zoë", "O'Brien-Núñez", "acme.com") == (
        "zoe.obriennunez@acme.com"
    )


def test_a_missing_name_gives_no_address() -> None:
    assert build_address("{first}.{last}", "Jane", "", "acme.com") is None
    assert build_address("{first}", "", "Doe", "acme.com") is None


@pytest.mark.parametrize(
    ("email", "pattern"),
    [
        ("jane.doe@acme.com", "{first}.{last}"),
        ("jdoe@acme.com", "{f}{last}"),
        ("jane@acme.com", "{first}"),
        ("JANE.DOE@ACME.COM", "{first}.{last}"),
        ("info@acme.com", None),
        ("jane.d.doe@acme.com", None),
    ],
)
def test_the_pattern_behind_an_address_is_recognised(email: str, pattern: str | None) -> None:
    assert infer_pattern(email, "Jane", "Doe") == pattern


@pytest.mark.parametrize(
    ("email", "result"),
    [
        ("jane.doe@acme.com", True),
        ("j.doe@acme.com", True),
        ("sales@acme.com", False),
        ("info@acme.com", False),
        ("do@acme.com", False),
    ],
)
def test_a_published_address_is_matched_to_a_person_by_surname(email: str, result: bool) -> None:
    assert matches_person(email, "Jane", "Doe") is result
