"""Choosing the database: one switch, with both connections kept side by side."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from outbound.config import Settings

SUPABASE = "postgresql://postgres.ref:pw@aws-0-x.pooler.supabase.com:5432/postgres"


def test_by_default_the_local_sqlite_file_is_used() -> None:
    assert Settings().database_url == "sqlite:///outbound.db"


def test_the_switch_picks_postgres_and_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URL", SUPABASE)
    monkeypatch.setenv("SQLITE_PATH", "local.db")
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    assert Settings().database_url == SUPABASE
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    assert Settings().database_url == "sqlite:///local.db"


def test_postgres_without_a_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    with pytest.raises(ValidationError, match="POSTGRES_URL is not set"):
        Settings()


def test_an_explicit_database_url_wins_over_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_URL", SUPABASE)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///other.db")
    assert Settings().database_url == "sqlite:///other.db"
