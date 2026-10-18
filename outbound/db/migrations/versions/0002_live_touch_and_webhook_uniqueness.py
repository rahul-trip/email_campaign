"""Uniqueness rules found while hardening for live use.

1. ``messages``: one *live* message per touch. A cancelled or rejected message no longer blocks
   a new first email for the same person (needed when a lead is released after a policy change
   or a hold).
2. ``import_batches``: one batch per webhook event id, so two simultaneous deliveries of the
   same event cannot both import.
3. ``workspaces``: names are unique, because they are how a workspace is looked up.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIVE = "state NOT IN ('cancelled', 'rejected')"
WEBHOOK = "source = 'webhook'"


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("uq_messages_company_id_contact_id_step", type_="unique")
    op.create_index(
        "ux_messages_live_touch",
        "messages",
        ["company_id", "contact_id", "step"],
        unique=True,
        sqlite_where=sa.text(LIVE),
        postgresql_where=sa.text(LIVE),
    )
    op.create_index(
        "ux_import_batches_webhook",
        "import_batches",
        ["workspace_id", "source", "filename"],
        unique=True,
        sqlite_where=sa.text(WEBHOOK),
        postgresql_where=sa.text(WEBHOOK),
    )
    with op.batch_alter_table("workspaces") as batch:
        batch.create_unique_constraint("uq_workspaces_name", ["name"])


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_constraint("uq_workspaces_name", type_="unique")
    op.drop_index("ux_import_batches_webhook", table_name="import_batches")
    op.drop_index("ux_messages_live_touch", table_name="messages")
    with op.batch_alter_table("messages") as batch:
        batch.create_unique_constraint(
            "uq_messages_company_id_contact_id_step", ["company_id", "contact_id", "step"]
        )
