"""Why a lead failed: a broken step, or "nobody to write to".

``companies.failure_kind`` is set when a lead moves to ``failed`` and cleared when it leaves.
Leads already failed are read from their last error: the two stages that answer "no person" or
"no address" use fixed wording.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = "'error', 'no_person', 'no_email'"


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("failure_kind", sa.String(length=40), nullable=True))
        batch.create_check_constraint(
            op.f("ck_companies_failure_kind"), sa.text(f"failure_kind IN ({KINDS})")
        )
    op.execute(
        "UPDATE companies SET failure_kind = 'no_email' "
        "WHERE status = 'failed' AND last_error LIKE 'no valid email found%'"
    )
    op.execute(
        "UPDATE companies SET failure_kind = 'no_person' WHERE status = 'failed' "
        "AND failure_kind IS NULL AND failed_stage IN ('contacts', 'email') AND ("
        "last_error LIKE 'no decision-maker was found%' OR "
        "last_error LIKE 'everyone a search found%' OR "
        "last_error LIKE 'the only people found%' OR "
        "last_error LIKE 'people were found, but none is a decision-maker%' OR "
        "last_error LIKE 'nobody at this lead is a decision-maker%')"
    )
    op.execute(
        "UPDATE companies SET failure_kind = 'error' WHERE status = 'failed' AND failure_kind IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_constraint(op.f("ck_companies_failure_kind"), type_="check")
        batch.drop_column("failure_kind")
