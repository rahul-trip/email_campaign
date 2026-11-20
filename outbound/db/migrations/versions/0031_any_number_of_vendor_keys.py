"""A vendor may have any number of live keys, not just three.

Migration 0027 limited a vendor to slots 1 to 3. The limit goes; a slot must still be 1 or more.
Each call still uses one live key at random (``outbound/providers/keypool.py``).

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("platform_credentials") as batch:
        batch.drop_constraint(op.f("ck_platform_credentials_slot_range"), type_="check")
        batch.create_check_constraint(op.f("ck_platform_credentials_slot_positive"), "slot >= 1")


def downgrade() -> None:
    # Slots above 3 cannot stay. Their keys are deleted, not retired: a retired row keeps its
    # slot, and the old constraint would refuse it.
    op.execute("DELETE FROM platform_credentials WHERE slot > 3")
    with op.batch_alter_table("platform_credentials") as batch:
        batch.drop_constraint(op.f("ck_platform_credentials_slot_positive"), type_="check")
        batch.create_check_constraint(
            op.f("ck_platform_credentials_slot_range"), "slot BETWEEN 1 AND 3"
        )
