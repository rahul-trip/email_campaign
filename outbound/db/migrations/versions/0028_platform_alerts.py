"""Notifications for the platform's own staff: a vendor key refused or out of credit, a crash.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_notifications_notification_kind"
BEFORE = (
    "'join_requested', 'join_approved', 'join_rejected', 'drafts_ready', 'hot_lead',"
    " 'needs_attention', 'auto_approved', 'run_finished', 'run_failed', 'discovery_paused',"
    " 'account'"
)
AFTER = BEFORE + ", 'platform_alert'"


def _set(values: str) -> None:
    with op.batch_alter_table("notifications") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), sa.text(f"kind IN ({values})"))


def upgrade() -> None:
    _set(AFTER)


def downgrade() -> None:
    # BEFORE is a constant list of the old enum values: nothing here comes from outside.
    op.execute(sa.text(f"DELETE FROM notifications WHERE kind NOT IN ({BEFORE})"))  # noqa: S608
    _set(BEFORE)
