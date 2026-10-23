from __future__ import annotations

from outbound.domain.slugs import MAX_LENGTH, slugify, unique_slug


def test_a_slug_is_short_plain_and_never_empty() -> None:
    assert slugify("Acme Énergie Ltd.") == "acme-energie-ltd"
    assert slugify("  --  ") == "workspace"
    assert len(slugify("x" * 200)) == MAX_LENGTH


def test_a_taken_slug_gets_a_number() -> None:
    assert unique_slug("Acme", set()) == "acme"
    assert unique_slug("Acme", {"acme"}) == "acme-2"
    assert unique_slug("Acme", {"acme", "acme-2"}) == "acme-3"
    long = "y" * MAX_LENGTH
    assert len(unique_slug(long, {long})) == MAX_LENGTH
