"""Column types that behave the same on SQLite and Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

# jsonb on Postgres, JSON text on SQLite.
Json = sa.JSON().with_variant(JSONB(), "postgresql")


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC in and out. SQLite drops the zone, so it is restored on the way out
    and naive values are refused on the way in."""

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: use a timezone-aware UTC value")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def enum_type(enum_class: type[StrEnum], name: str) -> sa.Enum:
    """A text column limited by a CHECK constraint generated from the domain enum.

    Not a native database enum: adding a value is then a one-line migration on both databases.
    """
    return sa.Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=40,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_dict(value: Any) -> dict[str, Any] | None:
    return None if value is None else dict(value)
