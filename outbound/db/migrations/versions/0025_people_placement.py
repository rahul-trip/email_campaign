"""People a search found who work somewhere else.

``contacts.status`` gains ``not_here`` and ``contacts.placement_note`` says why a person is
unconfirmed or not here. A person set aside is kept, so a rerun of research does not add them
back.

The CHECK is dropped and recreated by name (see migration 0003). The downgrade refuses to run
while ``not_here`` people exist: turning them into anything else would be a guess.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_contacts_contact_status"
OLD = "'unconfirmed', 'candidate', 'active', 'bounced', 'referred_away', 'opted_out', 'forgotten'"
NEW = "'unconfirmed', 'not_here', 'candidate', 'active', 'bounced', 'referred_away', 'opted_out', 'forgotten'"


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.add_column(sa.Column("placement_note", sa.String(500), nullable=True))
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), sa.text(f"status IN ({NEW})"))


def downgrade() -> None:
    left = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM contacts WHERE status = 'not_here'"))
        .scalar_one()
    )
    if left:
        raise RuntimeError(f"{left} not_here contact(s) exist; remove them before downgrading")
    with op.batch_alter_table("contacts") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), sa.text(f"status IN ({OLD})"))
        batch.drop_column("placement_note")
