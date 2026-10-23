"""One running pipeline per workspace, and a heartbeat so a dead worker's run can be recovered.

1. ``runs.heartbeat_at``: the runner touches it between leads. A ``running`` run with no recent
   heartbeat belonged to a worker that stopped, and is failed so it does not block the queue.
2. ``ux_runs_one_running_pipeline``: at most one ``running`` pipeline run per workspace, so two
   runs (the worker, a CLI ``run``, a tick) cannot pay twice for the same vendor call. Older
   duplicates left by a crashed worker are failed first, keeping the newest.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNNING_PIPELINE = "status = 'running' AND kind = 'pipeline'"


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        sa.text(
            "UPDATE runs SET status = 'failed' "
            "WHERE status = 'running' AND kind = 'pipeline' AND id NOT IN ("
            "  SELECT keep FROM (SELECT MAX(id) AS keep FROM runs"
            "   WHERE status = 'running' AND kind = 'pipeline' GROUP BY workspace_id) AS newest)"
        )
    )
    op.create_index(
        "ux_runs_one_running_pipeline",
        "runs",
        ["workspace_id"],
        unique=True,
        sqlite_where=sa.text(RUNNING_PIPELINE),
        postgresql_where=sa.text(RUNNING_PIPELINE),
    )


def downgrade() -> None:
    op.drop_index("ux_runs_one_running_pipeline", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("heartbeat_at")
