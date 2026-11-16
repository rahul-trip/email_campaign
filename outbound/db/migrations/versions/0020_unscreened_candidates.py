"""A verdict for companies discovery found but the model could not judge.

A screening reply that failed (cut off at the token limit, in production) made discovery fall
back to word matching, which rejected nearly everything and, because a company is never screened
twice, rejected it for good. Those companies get a verdict of their own, ``unscreened``, and the
next run screens them again.

This revision also puts back the companies already lost that way: a candidate that was
``rejected`` with no screening score, for the reason word matching gives when no word of the
brief is in a description, goes back to ``unscreened``.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_discovery_candidates_candidate_verdict"
BEFORE = "'accepted', 'rejected', 'unresolved', 'already_lead', 'over_limit'"
AFTER = BEFORE + ", 'unscreened'"
# What ``services.discovery._by_words`` said when no word of the brief was in the description.
BY_WORDS = "nothing it says matches the brief"


def _set(values: str) -> None:
    with op.batch_alter_table("discovery_candidates") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), sa.text(f"verdict IN ({values})"))


def upgrade() -> None:
    _set(AFTER)
    op.execute(
        sa.text(
            "UPDATE discovery_candidates SET verdict = 'unscreened', "
            "reason = 'rejected by word matching when the model could not answer; screened again' "
            "WHERE verdict = 'rejected' AND screen_score IS NULL AND reason = :reason"
        ).bindparams(reason=BY_WORDS)
    )


def downgrade() -> None:
    op.execute("UPDATE discovery_candidates SET verdict = 'rejected' WHERE verdict = 'unscreened'")
    _set(BEFORE)
