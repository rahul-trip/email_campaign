"""The composition root: the one place that builds the real objects and wires them together.

Nothing else constructs an engine or reads the settings, so tests can build the same objects
with a different database and fakes, and nothing is a hidden global.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, inspect

from outbound.config import Settings
from outbound.db.session import make_engine, make_session_factory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.errors import ConfigurationError


@dataclass(frozen=True)
class Container:
    settings: Settings
    engine: Engine
    uow: UnitOfWorkFactory

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
        with self.uow.admin() as admin:
            found = admin.workspaces.by_name(name)
        if found is None:
            raise ConfigurationError(f"no workspace named {name!r}: run `uv run outbound seed`")
        return found.id


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    engine = make_engine(settings.database_url, pool_size=settings.database_pool_size)
    return Container(settings, engine, UnitOfWorkFactory(make_session_factory(engine)))
