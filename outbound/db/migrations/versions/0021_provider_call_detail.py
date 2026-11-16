"""What each vendor call asked and got, in words, for the lead page.

``provider_calls`` kept only a hash of the request, so the lead page could not say what was
searched for. ``detail`` is ``{"asked": ..., "got": ...}``, a line each. It can name a person or
an address, like the stored answer, so erasing a person blanks it too. Older rows have none.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("provider_calls") as batch:
        batch.add_column(sa.Column("detail", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider_calls") as batch:
        batch.drop_column("detail")
