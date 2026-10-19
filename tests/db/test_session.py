"""Database URLs as hosts hand them out, and the engine settings a hosted pooler needs."""

from __future__ import annotations

import pytest

from outbound.db.session import make_engine, normalise_url


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Supabase's pooler string, copied from its dashboard
        (
            "postgresql://postgres.ref:pw@aws-0-x.pooler.supabase.com:5432/postgres",
            "postgresql+psycopg://postgres.ref:pw@aws-0-x.pooler.supabase.com:5432/postgres",
        ),
        ("postgres://u:pw@h/db?sslmode=require", "postgresql+psycopg://u:pw@h/db?sslmode=require"),
        ("postgresql+psycopg://u:pw@h/db", "postgresql+psycopg://u:pw@h/db"),
        ("sqlite:///outbound.db", "sqlite:///outbound.db"),
    ],
)
def test_postgres_urls_without_a_driver_use_psycopg_3(given: str, expected: str) -> None:
    assert normalise_url(given) == expected


def test_a_postgres_engine_keeps_a_small_checked_pool() -> None:
    engine = make_engine("postgresql://u:pw@h/db", pool_size=3)
    assert engine.dialect.driver == "psycopg"
    assert engine.pool.size() == 3  # type: ignore[attr-defined]
    assert engine.pool._max_overflow == 0  # type: ignore[attr-defined]
    assert engine.pool._pre_ping is True
    engine.dispose()
