"""The frozen migration must build exactly what the models describe."""

from __future__ import annotations

import re

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine.interfaces import ReflectedCheckConstraint

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
    "users", "memberships", "auth_tokens", "sessions", "audit_log",
}  # fmt: skip


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_the_models_describe_exactly_the_tables_of_the_spec() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert len(EXPECTED_TABLES) == 22  # schema v1's 17, and Phase 6b's five identity tables


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
    assert len(_enum_columns()) == 32


@pytest.fixture(scope="module")
def migrated_checks(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, list[ReflectedCheckConstraint]]:
    """Every table's check constraints, from one migrated database shared by the enum tests.

    On Postgres the session database (already migrated by the ``engine`` fixture) is read.
    """
    from tests.db.conftest import TEST_DATABASE_URL

    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path_factory.mktemp('checks') / 'checks.db'}"
    migrate.upgrade(url)
    engine = create_engine(url)
    try:
        found = inspect(engine)
        return {name: found.get_check_constraints(name) for name in EXPECTED_TABLES}
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("table", "enum", "column"), _enum_columns(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_each_check_constraint_allows_exactly_the_values_of_its_enum(
    migrated_checks: dict[str, list[ReflectedCheckConstraint]],
    table: str,
    enum: sa.Enum,
    column: str,
) -> None:
    checks = migrated_checks[table]
    wanted_name = f"ck_{table}_{enum.name}"
    (check,) = [c for c in checks if c["name"] == wanted_name]
    allowed = set(re.findall(r"'([^']+)'", check["sqltext"]))
    assert allowed == set(enum.enums), f"{table}.{column}"


def test_tenant_bound_keys_refuse_to_migrate_over_a_cross_workspace_link(fresh_url: str) -> None:
    """Migration 0007 checks first: a row already pointing into another workspace stops it."""
    migrate.upgrade(fresh_url, "0006")
    engine = create_engine(fresh_url)
    try:
        with engine.begin() as connection:
            now = "2026-10-23 00:00:00+00:00"
            for ws in ("w1", "w2"):
                connection.execute(
                    sa.text(
                        "INSERT INTO workspaces (id, name, sender_profile, settings, created_at, "
                        "updated_at) VALUES (:id, :id, '{}', '{}', :now, :now)"
                    ),
                    {"id": ws, "now": now},
                )
            connection.execute(
                sa.text(
                    "INSERT INTO campaigns (id, workspace_id, name, target_titles, "
                    "research_questions, cadence_days, min_fit_score, status, created_at, "
                    "updated_at) VALUES ('c2', 'w2', 'theirs', '[]', '[]', '[]', 60, 'active', "
                    ":now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO companies (id, workspace_id, campaign_id, domain, source, "
                    "priority, status, legal_entity_type, attempts, manual_fields, row_version, "
                    "created_at, updated_at) VALUES ('x1', 'w1', 'c2', 'acme.com', 'manual', 5, "
                    "'new', 'unknown', 0, '[]', 1, :now, :now)"
                ),
                {"now": now},
            )
    finally:
        engine.dispose()
    with pytest.raises(RuntimeError, match=r"companies\.campaign_id"):
        migrate.upgrade(fresh_url)
