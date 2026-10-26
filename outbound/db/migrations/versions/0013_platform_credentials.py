"""Vendor API keys in the database (Phase 6d.4).

``platform_credentials``: one row per version of a vendor key, encrypted. A platform table, so no
row-level security: only the platform role holds a grant, and the app role holds none.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WHEN = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "platform_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("vendor", sa.String(length=60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("retired_at", WHEN, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_credentials")),
        sa.UniqueConstraint(
            "vendor", "version", name=op.f("uq_platform_credentials_vendor_version")
        ),
    )
    op.create_index(op.f("ix_platform_credentials_vendor"), "platform_credentials", ["vendor"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON platform_credentials TO outbound_platform"
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_platform_credentials_vendor"), table_name="platform_credentials")
    op.drop_table("platform_credentials")
