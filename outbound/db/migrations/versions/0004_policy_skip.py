"""The operator can skip the country rule for one lead, from a stage onward.

``companies.policy_skip_from``: empty, or the first stage (``gate``, ``contacts``, ``email``,
``copy``, ``deliver``) from which the country rule is not applied to this lead. Who skipped it,
when and why are in the ``policy_skip_granted`` event. The workspace-wide switch lives in
``workspaces.settings`` and needs no column.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGES = "'gate', 'contacts', 'email', 'copy', 'deliver'"


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("policy_skip_from", sa.String(length=40), nullable=True))
        batch.create_check_constraint(
            op.f("ck_companies_policy_stage"), sa.text(f"policy_skip_from IN ({STAGES})")
        )


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_constraint(op.f("ck_companies_policy_stage"), type_="check")
        batch.drop_column("policy_skip_from")
