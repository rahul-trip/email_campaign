"""AI credits: one pool per workspace, used by every vendor and model call.

1. ``provider_calls.credits_milli`` and ``runs.credits_milli``: the AI credits a call (or a run)
   used, in thousandths, stamped by the meter when the call is made. Calls made before this
   migration are not converted: they keep 0 credits and their recorded cost, so only calls
   metered from now on count against a plan.
2. ``credit_grants.step`` may be empty: a grant is now AI credits, not a step. Grants made before
   become credits at ``CREDITS_PER_STEP`` each (about what one lead's step uses).
3. Per-step limit overrides (``limit.<step>``) are withdrawn; a per-prospect budget override
   becomes AI credits.
4. The plan catalog gains Starter and Pro if it lacks them; each workspace's "budget per
   prospect" setting becomes AI credits.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-18
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREDIT_VALUE = 10_000  # micro-USD per AI credit: the default rate
CREDITS_PER_STEP = 20
OLD_BUDGET, NEW_BUDGET = "budget_per_prospect_micro_usd", "budget_per_prospect_credits"
STARTER = {
    "code": "starter", "name": "Starter", "monthly_credits": 2000, "seats": 3, "mailboxes": 2,
    "active_campaigns": 2, "max_leads_per_run": None, "max_prospect_budget_credits": 50,
    "features": ["directory_bypass", "discovery"], "access_days": None,
}  # fmt: skip
PRO = {
    "code": "pro", "name": "Pro", "monthly_credits": 10000, "seats": 10, "mailboxes": 5,
    "active_campaigns": 5, "max_leads_per_run": None, "max_prospect_budget_credits": 100,
    "features": ["directory_bypass", "discovery", "follow_ups"], "access_days": None,
}  # fmt: skip


def _credits(micro_usd: Any) -> int | None:
    return None if micro_usd is None else -(-int(micro_usd) // CREDIT_VALUE)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _write_json(bind: sa.Connection, table: str, column: str, value: Any, row_id: str) -> None:
    """Replace one row's JSON column (JSONB on Postgres needs the cast)."""
    param = "CAST(:j AS JSONB)" if bind.dialect.name == "postgresql" else ":j"
    # Table and column are constants of this migration: nothing here comes from outside.
    sql = f"UPDATE {table} SET {column} = {param} WHERE id = :id"  # noqa: S608
    bind.execute(sa.text(sql), {"j": json.dumps(value), "id": row_id})


def upgrade() -> None:
    for table in ("provider_calls", "runs"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("credits_milli", sa.BigInteger(), server_default="0", nullable=False)
            )
    with op.batch_alter_table("credit_grants") as batch:
        batch.alter_column("step", existing_type=sa.String(length=40), nullable=True)
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE credit_grants SET amount = amount * :per, "
            "note = CASE WHEN note = '' THEN :mark ELSE note || ' ' || :mark END "
            "WHERE step IS NOT NULL"
        ),
        {"per": CREDITS_PER_STEP, "mark": f"(converted to AI credits, {CREDITS_PER_STEP} a step)"},
    )
    bind.execute(
        sa.text(
            "UPDATE entitlement_overrides SET revoked_at = CURRENT_TIMESTAMP "
            "WHERE key LIKE 'limit.%' AND revoked_at IS NULL"
        )
    )
    for row in bind.execute(
        sa.text("SELECT id, value FROM entitlement_overrides WHERE key = 'max_prospect_budget'")
    ):
        value = (_json(row.value) or {}).get("value")
        _write_json(bind, "entitlement_overrides", "value", {"value": _credits(value)}, row.id)
    _catalog(bind)
    for row in bind.execute(sa.text("SELECT id, settings FROM workspaces")):
        settings = _json(row.settings) or {}
        if OLD_BUDGET not in settings:
            continue
        settings[NEW_BUDGET] = _credits(settings.pop(OLD_BUDGET))
        _write_json(bind, "workspaces", "settings", settings, row.id)


def _catalog(bind: sa.Connection) -> None:
    row = bind.execute(sa.text("SELECT data FROM platform_settings WHERE id = 'platform'")).first()
    if row is None:
        return  # never saved: the code's defaults already have all three plans
    data = _json(row.data) or {}
    plans = data.get("plans") or []
    codes = {p.get("code") for p in plans}
    plans += [p for p in (STARTER, PRO) if p["code"] not in codes]
    data["plans"] = plans
    _write_json(bind, "platform_settings", "data", data, "platform")


def downgrade() -> None:
    bind = op.get_bind()
    for row in bind.execute(sa.text("SELECT id, settings FROM workspaces")):
        settings = _json(row.settings) or {}
        if NEW_BUDGET not in settings:
            continue
        credits = settings.pop(NEW_BUDGET)
        settings[OLD_BUDGET] = None if credits is None else int(credits) * CREDIT_VALUE
        _write_json(bind, "workspaces", "settings", settings, row.id)
    # A grant without a step cannot be one again: it is withdrawn.
    op.execute("DELETE FROM credit_grants WHERE step IS NULL")
    with op.batch_alter_table("credit_grants") as batch:
        batch.alter_column("step", existing_type=sa.String(length=40), nullable=False)
    for table in ("runs", "provider_calls"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("credits_milli")
