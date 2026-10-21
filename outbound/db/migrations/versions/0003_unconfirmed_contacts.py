"""Contacts a search found but could not place at the company.

``contacts.status`` gains ``unconfirmed``: a person from a public search whose employer did not
clearly match the company. Such a person is not worked on until the operator confirms them.

The CHECK is dropped and recreated by name, because SQLite's batch mode does not reliably carry
a CHECK constraint across the table copy. The downgrade refuses to run while unconfirmed people
exist: turning them into candidates would make them workable without anyone confirming them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_contacts_contact_status"
OLD = "'candidate', 'active', 'bounced', 'referred_away', 'opted_out', 'forgotten'"
NEW = "'unconfirmed', " + OLD


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), sa.text(f"status IN ({NEW})"))


def downgrade() -> None:
    left = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM contacts WHERE status = 'unconfirmed'"))
        .scalar_one()
    )
    if left:
        raise RuntimeError(
            f"{left} unconfirmed contact(s) exist; confirm or remove them before downgrading"
        )
    with op.batch_alter_table("contacts") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), sa.text(f"status IN ({OLD})"))
