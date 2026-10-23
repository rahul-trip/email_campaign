"""Errors the data layer raises, so callers never see SQLAlchemy exceptions."""

from __future__ import annotations


class NotFound(LookupError):
    """No such row in this workspace (a row in another workspace counts as not found)."""


class ConcurrencyConflict(Exception):
    """The row changed since it was read: reload it and try again."""


class RunInProgress(Exception):
    """Another pipeline run is already running in this workspace; this one must wait."""
