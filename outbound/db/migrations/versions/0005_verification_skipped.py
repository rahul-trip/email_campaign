"""The operator can write to an address without (or despite) a verifier's answer.

``contact_emails.verification_skipped``: set by the operator for one address. Such an address is
treated as sendable whatever its status, the verifier is not called for it, and approving an
email to it asks the operator to confirm. Suppression still applies. Who set it, when and why
are in the ``email_verification_skipped`` event.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("contact_emails") as batch:
        batch.add_column(
            sa.Column(
                "verification_skipped", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("contact_emails") as batch:
        batch.drop_column("verification_skipped")
