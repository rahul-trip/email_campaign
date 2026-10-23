"""Moving the single-operator install to the first customer (Phase 6b.7)."""

from __future__ import annotations

from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.identity import normalise_email
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.domain.enums import MembershipRole, PlatformRole
from scripts.migrate_first_tenant import migrate

PASSWORD = "plum kettle orbit lantern meadow"
EMAIL = "Sam@Quantra.example"


def run(engine: Engine, platform_engine: Engine, workspace: str, *, apply: bool) -> list[str]:
    said: list[str] = []
    container = container_for(Settings(_env_file=None), engine, platform_engine)
    migrate(
        container, workspace=workspace, name="Quantra Energy", email=EMAIL, apply=apply,
        password=lambda: PASSWORD, say=said.append,
    )  # fmt: skip
    return said


def test_a_dry_run_changes_nothing(
    engine: Engine, platform_engine: Engine, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    said = run(engine, platform_engine, "acme", apply=False)
    assert said[-1].startswith("dry run")
    with platform() as p:
        assert p.workspaces.get(ws).name != "Quantra Energy"  # type: ignore[union-attr]
    container = container_for(Settings(_env_file=None), engine, platform_engine)
    with container.identity() as ids:
        assert ids.users.by_email(EMAIL) is None


def test_applying_renames_the_workspace_and_makes_the_operator_its_admin_and_superadmin(
    engine: Engine, platform_engine: Engine, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    run(engine, platform_engine, "acme", apply=True)
    run(engine, platform_engine, "acme", apply=True)  # twice is harmless
    with platform() as p:
        moved = p.workspaces.get(ws)
    assert moved is not None and (moved.name, moved.slug) == ("Quantra Energy", "quantra-energy")
    container = container_for(Settings(_env_file=None), engine, platform_engine)
    with container.identity() as ids:
        user = ids.users.by_email(EMAIL)
        assert user is not None and user.email == normalise_email(EMAIL)
        assert user.platform_role is PlatformRole.SUPERADMIN
        membership = ids.memberships.get(ws, user.id)
    assert membership is not None and membership.role is MembershipRole.ADMIN


def test_an_unknown_workspace_is_reported(engine: Engine, platform_engine: Engine) -> None:
    assert run(engine, platform_engine, "nope", apply=True) == [
        "no workspace 'nope'; nothing to do"
    ]
