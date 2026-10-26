"""Ask for a fresh email search for one person (the lead page's "Find email again").

``contacts.refresh_email`` is set by the button and cleared when the email step has tried that
person again; while it is set, the step ignores earlier cached vendor answers for them.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.add_column(
            sa.Column("refresh_email", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.drop_column("refresh_email")
