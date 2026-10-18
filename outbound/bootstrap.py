"""The composition root: the one place that builds the real objects and wires them together.

Nothing else constructs an engine or reads the settings, so tests can build the same objects
with a different database and fakes, and nothing is a hidden global.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from outbound.config import Settings
from outbound.db.session import make_engine, make_session_factory
from outbound.db.uow import UnitOfWorkFactory


@dataclass(frozen=True)
class Container:
    settings: Settings
    engine: Engine
    uow: UnitOfWorkFactory


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    return Container(settings, engine, UnitOfWorkFactory(make_session_factory(engine)))
