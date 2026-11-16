"""The app role may delete discovery candidates that are still waiting.

Changing a campaign's brief or the sender profile forgets the companies that were waiting to be
added (``SettingsService``), so the next run judges them against the new brief. Migration 0019
granted only read, add and update, so that delete was refused on PostgreSQL.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "outbound_app"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT DELETE ON discovery_candidates TO {APP}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE DELETE ON discovery_candidates FROM {APP}")
