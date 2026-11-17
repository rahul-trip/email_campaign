"""A vendor may have up to three live keys, one per slot.

Each call to a vendor picks one of its live keys at random and, when that key is refused, rate
limited or out of credit, tries the others (``outbound/providers/keypool.py``). Every existing
key becomes slot 1, so nothing changes until a second key is added.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("platform_credentials") as batch:
        batch.add_column(sa.Column("slot", sa.Integer(), server_default="1", nullable=False))
        batch.create_check_constraint(
            op.f("ck_platform_credentials_slot_range"), "slot BETWEEN 1 AND 3"
        )


def downgrade() -> None:
    # Only one key per vendor can stay live: the extra slots' keys are retired, not deleted.
    op.execute(
        "UPDATE platform_credentials SET active = false, retired_at = CURRENT_TIMESTAMP "
        "WHERE slot > 1 AND active"
    )
    with op.batch_alter_table("platform_credentials") as batch:
        batch.drop_constraint(op.f("ck_platform_credentials_slot_range"), type_="check")
        batch.drop_column("slot")
