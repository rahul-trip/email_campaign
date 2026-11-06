"""Who a campaign looks for, in parts the engine can use (``campaigns.icp_brief``).

A model drafts the brief from the campaign's description and the sender profile, and the
operator can edit it. Discovery picks its sources and searches from it, screening keeps or drops
each company found against it, and research qualifies a lead against it. JSON, shaped by
``outbound.domain.brief.Brief``; empty until first drafted.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("icp_brief", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("icp_brief")
