"""The composition root: the one place that builds the real objects and wires them together.

Nothing else constructs an engine or reads the settings, so tests can build the same objects
with a different database and fakes, and nothing is a hidden global.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, inspect

from outbound.config import Settings
from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.session import make_engine, make_session_factory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.errors import ConfigurationError


@dataclass(frozen=True)
class Container:
    settings: Settings
    engine: Engine
    uow: UnitOfWorkFactory
    platform: PlatformUnitOfWorkFactory
    identity: IdentityUnitOfWorkFactory

    def workspace_id(self, name: str) -> str:
        """The id of the named workspace, or a ConfigurationError that says what to run.

        A database that was never set up has no tables at all, which would otherwise surface as
        a raw "no such table" error from deep inside the first query.
        """
        if not inspect(self.engine).has_table("workspaces"):
            raise ConfigurationError(
                "The database has not been set up yet. Run these two commands, then try again:\n"
                "  uv run outbound db upgrade\n"
                "  uv run outbound seed\n"
                f"(database: {self.engine.url.render_as_string(hide_password=True)})"
            )
        with self.platform() as platform:
            found = platform.workspaces.find(name)
        if found is None:
            raise ConfigurationError(f"no workspace named {name!r}: run `uv run outbound seed`")
        return found.id


def container_for(
    settings: Settings, engine: Engine, platform_engine: Engine | None = None
) -> Container:
    """Wire the unit-of-work factories over engines that already exist (tests, scripts).

    In production the platform engine connects as a different database role, one that may
    read every workspace; tenant work never uses it.
    """
    platform_sessions = make_session_factory(platform_engine or engine)
    sessions = make_session_factory(engine)
    return Container(
        settings,
        engine,
        UnitOfWorkFactory(sessions),
        PlatformUnitOfWorkFactory(platform_sessions),
        IdentityUnitOfWorkFactory(sessions),
    )


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    engine = make_engine(settings.database_url, pool_size=settings.database_pool_size)
    platform_engine = (
        engine
        if settings.platform_database_url == settings.database_url
        else make_engine(settings.platform_database_url, pool_size=2)
    )
    return container_for(settings, engine, platform_engine)
