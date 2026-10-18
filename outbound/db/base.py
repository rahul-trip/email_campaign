"""Declarative base, naming convention and the columns every table shares."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from outbound.db.types import UtcDateTime, utcnow
from outbound.domain.ids import new_id

# Stable constraint names keep Alembic migrations identical on SQLite and Postgres.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Identified:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id, sort_order=-30)


class Scoped(Identified):
    """Every row belongs to a workspace, which is also the Phase 6 row-level-security key."""

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True, sort_order=-20
    )


class AppendOnly(Scoped):
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, sort_order=100)


class Mutable(AppendOnly):
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow, sort_order=101
    )
