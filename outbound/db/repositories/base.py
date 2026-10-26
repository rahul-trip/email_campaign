"""Shared repository plumbing: workspace scoping, snapshots, and protected field updates."""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.models import EventRow
from outbound.db.types import utcnow
from outbound.domain.actors import is_operator
from outbound.domain.entities import Event
from outbound.domain.enums import EntityType


def snapshot[E](row: Any, entity: type[E]) -> E:
    """Copy a row into its entity. Field names match column names, so no mapping table."""
    names = [f.name for f in dataclasses.fields(entity)]  # type: ignore[arg-type]
    return entity(**{name: getattr(row, name) for name in names})


def plain(value: Any) -> Any:
    """Make a value safe to store in an event's JSON."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class EventRepository:
    """Append-only history. Other repositories write through it in their own transaction."""

    def __init__(self, session: Session, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def append(
        self,
        entity_type: EntityType,
        entity_id: str,
        type: str,
        actor: str,
        data: Mapping[str, Any],
    ) -> None:
        self._session.add(
            EventRow(
                workspace_id=self._workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                type=type,
                actor=actor,
                data=dict(data),
                created_at=utcnow(),
            )
        )

    def for_entities(self, entities: list[tuple[EntityType, str]]) -> list[Event]:
        """The history of several rows together, oldest first (for one lead's timeline)."""
        if not entities:
            return []
        stmt = (
            select(EventRow)
            .where(
                EventRow.workspace_id == self._workspace_id,
                or_(
                    *(
                        and_(EventRow.entity_type == kind, EventRow.entity_id == ident)
                        for kind, ident in entities
                    )
                ),
            )
            .order_by(EventRow.created_at, EventRow.id)
        )
        return [snapshot(row, Event) for row in self._session.scalars(stmt)]

    def for_run(self, run_id: str, types: Collection[str]) -> list[Event]:
        """Events a run recorded (their data carries its ``run_id``), oldest first."""
        stmt = (
            select(EventRow)
            .where(
                EventRow.workspace_id == self._workspace_id,
                EventRow.type.in_(list(types)),
                EventRow.data["run_id"].as_string() == run_id,
            )
            .order_by(EventRow.created_at, EventRow.id)
        )
        return [snapshot(row, Event) for row in self._session.scalars(stmt)]

    def latest(self, entity_type: EntityType, entity_id: str, type: str, limit: int) -> list[Event]:
        """The newest ``limit`` events of one type on one entity, oldest first."""
        stmt = (
            select(EventRow)
            .where(
                EventRow.workspace_id == self._workspace_id,
                EventRow.entity_type == entity_type,
                EventRow.entity_id == entity_id,
                EventRow.type == type,
            )
            .order_by(EventRow.created_at.desc(), EventRow.id.desc())
            .limit(limit)
        )
        return [snapshot(row, Event) for row in reversed(list(self._session.scalars(stmt)))]

    def for_entity(self, entity_type: EntityType, entity_id: str) -> list[Event]:
        stmt = (
            select(EventRow)
            .where(
                EventRow.workspace_id == self._workspace_id,
                EventRow.entity_type == entity_type,
                EventRow.entity_id == entity_id,
            )
            .order_by(EventRow.created_at, EventRow.id)
        )
        return [snapshot(row, Event) for row in self._session.scalars(stmt)]


class ScopedRepository:
    """Every query goes through ``_row`` or a statement that filters on the workspace."""

    def __init__(self, session: Session, workspace_id: str, events: EventRepository) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._events = events

    def _row[R](self, model: type[R], row_id: str) -> R:
        stmt = select(model).where(
            model.id == row_id,  # type: ignore[attr-defined]
            model.workspace_id == self._workspace_id,  # type: ignore[attr-defined]
        )
        row = self._session.scalars(stmt).one_or_none()
        if row is None:
            raise NotFound(f"{model.__name__} {row_id}")
        return row

    def _flush(self) -> None:
        try:
            self._session.flush()
        except StaleDataError as exc:
            raise ConcurrencyConflict("the row changed since it was read") from exc

    @staticmethod
    def _check_version(row: Any, expected_version: int) -> None:
        if row.row_version != expected_version:
            raise ConcurrencyConflict(
                f"expected version {expected_version}, found {row.row_version}"
            )

    def _apply_changes(
        self,
        row: Any,
        changes: Mapping[str, Any],
        *,
        editable: frozenset[str],
        actor: str,
        entity_type: EntityType,
    ) -> bool:
        """Apply field changes; return True if the row was modified.

        An operator's change always applies and the field is remembered in ``manual_fields``.
        The engine may not overwrite such a field: its value is recorded as an event instead,
        so the UI can still show both. Every change, applied or not, is an event.
        """
        operator = is_operator(actor)
        manual: list[str] = list(row.manual_fields or [])
        modified = False
        for name, new in changes.items():
            if name not in editable:
                raise ValueError(f"{name!r} cannot be changed here")
            old = getattr(row, name)
            if old == new:
                continue
            event = {"field": name, "old": plain(old), "new": plain(new), "source": actor}
            if not operator and name in manual:
                self._events.append(
                    entity_type, row.id, "field_changed", actor, {**event, "applied": False}
                )
                continue
            setattr(row, name, new)
            modified = True
            if operator and name not in manual:
                manual.append(name)
            self._events.append(
                entity_type, row.id, "field_changed", actor, {**event, "applied": True}
            )
        if modified:
            row.manual_fields = manual
        return modified
