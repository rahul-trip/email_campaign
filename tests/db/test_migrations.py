"""The frozen migration must build exactly what the models describe."""

from __future__ import annotations

import re

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from outbound.db import (
    migrate,
    models,  # noqa: F401  (registers the tables)
)
from outbound.db.base import Base

EXPECTED_TABLES = {
    "workspaces", "campaigns", "mailboxes", "country_policies", "suppressions",
    "import_batches", "import_rows",
    "companies", "contacts", "contact_emails", "notes", "consents",
    "messages", "inbound_messages",
    "runs", "provider_calls", "events",
}  # fmt: skip


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_the_models_describe_exactly_the_seventeen_tables_of_the_spec() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert len(EXPECTED_TABLES) == 17


def test_upgrade_builds_every_table_and_records_the_head_revision(fresh_url: str) -> None:
    migrate.upgrade(fresh_url)
    assert table_names(fresh_url) == EXPECTED_TABLES
    assert migrate.current_revision(fresh_url) == migrate.head_revision()


def test_downgrade_removes_everything_and_upgrade_can_run_again(fresh_url: str) -> None:
    migrate.upgrade(fresh_url)
    migrate.downgrade(fresh_url, "base")
    assert table_names(fresh_url) == set()
    assert migrate.current_revision(fresh_url) is None
    migrate.upgrade(fresh_url)
    assert table_names(fresh_url) == EXPECTED_TABLES


def test_upgrading_twice_is_harmless(fresh_url: str) -> None:
    migrate.upgrade(fresh_url)
    migrate.upgrade(fresh_url)
    assert migrate.current_revision(fresh_url) == migrate.head_revision()


def test_the_migrated_schema_matches_the_models(fresh_url: str) -> None:
    """Autogenerate finds nothing to add, drop or alter, so migration and models agree."""
    migrate.upgrade(fresh_url)
    engine = create_engine(fresh_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "render_as_batch": True}
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def _enum_columns() -> list[tuple[str, sa.Enum, str]]:
    found = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, sa.Enum):
                found.append((table.name, column.type, column.name))
    return found


def test_there_is_a_check_constraint_for_every_enum_column() -> None:
    assert len(_enum_columns()) == 25


@pytest.mark.parametrize(
    ("table", "enum", "column"), _enum_columns(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_each_check_constraint_allows_exactly_the_values_of_its_enum(
    fresh_url: str, table: str, enum: sa.Enum, column: str
) -> None:
    migrate.upgrade(fresh_url)
    engine = create_engine(fresh_url)
    try:
        checks = inspect(engine).get_check_constraints(table)
    finally:
        engine.dispose()
    wanted_name = f"ck_{table}_{enum.name}"
    (check,) = [c for c in checks if c["name"] == wanted_name]
    allowed = set(re.findall(r"'([^']+)'", check["sqltext"]))
    assert allowed == set(enum.enums), f"{table}.{column}"
