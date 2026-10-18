"""IDs, money, hashing and domain normalisation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from outbound.domain.domains import is_free_mail, is_platform, registrable_domain
from outbound.domain.hashing import hash_value
from outbound.domain.ids import new_id
from outbound.domain.money import format_usd, micro_to_usd, usd_to_micro


def test_ids_are_unique_and_sort_by_creation_time() -> None:
    ids = [new_id() for _ in range(200)]
    assert len(set(ids)) == 200
    assert ids == sorted(ids)
    assert len(ids[0]) == 36


@pytest.mark.parametrize(
    ("amount", "micro"),
    [("0.0025", 2_500), ("0.16", 160_000), ("1", 1_000_000), (Decimal("0.0000005"), 1), (0, 0)],
)
def test_dollars_become_whole_micro_dollars(amount: str | int | Decimal, micro: int) -> None:
    assert usd_to_micro(amount) == micro


def test_micro_dollars_round_trip_without_drift() -> None:
    assert micro_to_usd(2_500) == Decimal("0.0025")
    assert format_usd(160_000) == "$0.1600"
    assert sum(usd_to_micro("0.1") for _ in range(10)) == usd_to_micro("1")


def test_hashing_ignores_case_and_surrounding_space() -> None:
    assert hash_value("  Jane@Acme.COM ") == hash_value("jane@acme.com")
    assert hash_value("a@b.com") != hash_value("a@b.org")
    assert "jane" not in hash_value("jane@acme.com")


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("https://uk.Example.co.uk/about?x=1", "example.co.uk"),
        ("Jack@OpenClimateFix.org", "openclimatefix.org"),
        ("watttime.org/about", "watttime.org"),
        ("https://www.openclimatefix.org:8080/x", "openclimatefix.org"),
        ("  ACME.com  ", "acme.com"),
        ("http://localhost", None),
        ("not a domain", None),
        ("", None),
    ],
)
def test_registrable_domain(typed: str, expected: str | None) -> None:
    assert registrable_domain(typed) == expected


def test_free_mail_and_platform_lists() -> None:
    assert is_free_mail("gmail.com") and not is_free_mail("acme.com")
    assert is_platform("linkedin.com") and not is_platform("acme.com")
