"""A token purpose for the public "Remove my data" page (Phase 6g).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_auth_tokens_auth_token_purpose"


def _set(values: str) -> None:
    with op.batch_alter_table("auth_tokens") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), sa.text(f"purpose IN ({values})"))


def upgrade() -> None:
    _set("'invite', 'reset', 'remove_data'")


def downgrade() -> None:
    op.execute("DELETE FROM auth_tokens WHERE purpose = 'remove_data'")
    _set("'invite', 'reset'")
