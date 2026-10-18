"""Identifiers: UUIDv7 strings, which sort by creation time and map to Postgres ``uuid``."""

from __future__ import annotations

import uuid_utils


def new_id() -> str:
    return str(uuid_utils.uuid7())
