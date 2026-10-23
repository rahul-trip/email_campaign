"""Row-level security (Phase 6a): the database keeps workspaces apart even when application
code forgets to. These run on Postgres only, connected as the production roles; SQLite has no
row-level security, and there the application scoping tests carry the guarantee."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from outbound.db.isolation import isolation_problems, tenant_tables
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanySource
from tests.db.conftest import IS_POSTGRES

pytestmark = pytest.mark.skipif(not IS_POSTGRES, reason="row-level security is Postgres only")


def add(factory: UnitOfWorkFactory, workspace: str, domain: str) -> str:
    with factory(workspace) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL)
        uow.commit()
    return company.id


@pytest.fixture
def two_tenants(factory: UnitOfWorkFactory, ws: str, other_ws: str) -> Iterator[tuple[str, str]]:
    add(factory, ws, "mine.com")
    theirs = add(factory, other_ws, "theirs.com")
    yield ws, theirs


def test_a_query_without_any_workspace_filter_still_sees_only_its_own_rows(
    factory: UnitOfWorkFactory, two_tenants: tuple[str, str]
) -> None:
    """The Phase 6 gate: application scoping removed, row-level security alone holds."""
    ws, _ = two_tenants
    with factory(ws) as uow:
        domains = uow.session.execute(text("SELECT domain FROM companies")).scalars().all()
        everyone = uow.session.execute(text("SELECT id FROM workspaces")).scalars().all()
    assert domains == ["mine.com"]
    assert everyone == [ws]


def test_without_a_workspace_the_app_role_sees_nothing(
    engine: Engine, two_tenants: tuple[str, str]
) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM companies")).scalar_one() == 0


def test_a_write_into_another_workspace_is_refused(
    factory: UnitOfWorkFactory,
    platform: PlatformUnitOfWorkFactory,
    two_tenants: tuple[str, str],
    other_ws: str,
) -> None:
    ws, theirs = two_tenants
    with factory(ws) as uow:
        uow.session.execute(
            text("UPDATE companies SET name = 'hijacked' WHERE id = :id"), {"id": theirs}
        )
        uow.commit()
    with platform() as directory:  # invisible to the update, so untouched
        name = directory.session.execute(
            text("SELECT name FROM companies WHERE id = :id"), {"id": theirs}
        ).scalar_one()
        assert name is None
    with factory(ws) as uow, pytest.raises(DBAPIError, match="row-level security"):
        uow.session.execute(
            text(
                "INSERT INTO companies (id, workspace_id, domain, source, priority, status, "
                "legal_entity_type, attempts, manual_fields, row_version, created_at, "
                "updated_at) VALUES ('x', :other, 'sneaky.com', 'manual', 5, 'new', "
                "'unknown', 0, '[]', 1, now(), now())"
            ),
            {"other": other_ws},
        )


def test_the_platform_role_reads_every_workspace_but_cannot_change_their_rows(
    platform: PlatformUnitOfWorkFactory, two_tenants: tuple[str, str]
) -> None:
    with platform() as directory:
        domains = directory.session.execute(text("SELECT domain FROM companies")).scalars().all()
        assert sorted(domains) == ["mine.com", "theirs.com"]
        with pytest.raises(DBAPIError, match="permission denied"):
            directory.session.execute(text("UPDATE companies SET name = 'x'"))


def test_the_production_roles_pass_the_startup_check(engine: Engine) -> None:
    assert isolation_problems(engine) == []


def test_the_owner_fails_the_startup_check(owner_engine: Engine) -> None:
    problems = isolation_problems(owner_engine)
    assert any("superuser" in p or "owner" in p for p in problems)


def test_every_tenant_table_has_row_level_security_and_a_policy(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        unprotected = connection.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:t) AND NOT c.relrowsecurity"
            ),
            {"t": list(tenant_tables())},
        ).scalars()
        assert list(unprotected) == []
        without_policy = connection.execute(
            text(
                "SELECT t FROM unnest(CAST(:t AS text[])) t WHERE NOT EXISTS (SELECT 1 "
                "FROM pg_policies p WHERE p.tablename = t AND 'outbound_app' = ANY(p.roles))"
            ),
            {"t": list(tenant_tables())},
        ).scalars()
        assert list(without_policy) == []


def test_a_public_data_api_role_with_grants_fails_the_startup_check(
    owner_engine: Engine, engine: Engine
) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') "
                "THEN CREATE ROLE anon NOLOGIN; END IF; END $$"
            )
        )
        connection.execute(text("GRANT SELECT ON companies TO anon"))
    try:
        assert any("anon" in p for p in isolation_problems(engine))
    finally:
        with owner_engine.begin() as connection:
            connection.execute(text("REVOKE ALL ON companies FROM anon"))
    assert isolation_problems(engine) == []


def test_a_read_only_unit_of_work_cannot_write(factory: UnitOfWorkFactory, ws: str) -> None:
    """The superadmin view (Phase 6b): even a write that slipped past the permission check
    fails in the database."""
    add(factory, ws, "seen.com")
    with factory.reading_only()(ws) as uow:
        assert [c.domain for c in uow.companies.search()[0]] == ["seen.com"]
        with pytest.raises(DBAPIError):
            uow.companies.create(domain="written.com", source=CompanySource.MANUAL)
            uow.commit()
