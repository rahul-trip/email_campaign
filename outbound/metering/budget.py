"""Spend caps, checked before a paid call is made.

Two caps exist: a monthly cap per provider, the platform's own safety net against a runaway loop,
in dollars from the environment; and the customer's budget per prospect, in AI credits. Both
compare what the ledger already holds plus the expected price of the call about to be made, so a
call that would cross the line is refused rather than made and regretted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from outbound.db.uow import UnitOfWork
from outbound.domain.credits import credits_for, milli

SETTING = "budget_per_prospect_credits"


@dataclass(frozen=True)
class BudgetPolicy:
    monthly_caps: Mapping[str, int] = field(default_factory=dict)  # provider -> micro-USD
    per_prospect: int | None = None  # AI credits; None means no ceiling
    # Read the per-prospect ceiling from the workspace at every check, so a change made in the
    # app applies to the next paid call without restarting the worker.
    live: bool = False

    @classmethod
    def from_workspace_settings(
        cls, settings: Mapping[str, object], monthly_caps: Mapping[str, int] | None = None
    ) -> BudgetPolicy:
        ceiling = settings.get(SETTING)
        return cls(
            monthly_caps=dict(monthly_caps or {}),
            per_prospect=ceiling if isinstance(ceiling, int) else None,
        )

    @classmethod
    def live_from(cls, monthly_caps: Mapping[str, int] | None = None) -> BudgetPolicy:
        return cls(monthly_caps=dict(monthly_caps or {}), live=True)

    def ceiling(self, uow: UnitOfWork) -> int | None:
        """The per-prospect ceiling in force now."""
        if not self.live:
            return self.per_prospect
        value = uow.workspace_settings().get(SETTING)
        return value if isinstance(value, int) else None


def month_start(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def check_budget(
    policy: BudgetPolicy,
    uow: UnitOfWork,
    *,
    provider: str,
    expected_cost: int,
    company_id: str | None,
    now: datetime,
) -> str | None:
    """Why the call must not be made, or ``None`` if it may go ahead."""
    cap = policy.monthly_caps.get(provider)
    if cap is not None:
        spent = uow.calls.spend_since(provider, month_start(now))
        if spent + expected_cost > cap:
            return f"the platform's monthly limit for {provider} is reached"
    ceiling = policy.ceiling(uow) if company_id is not None else None
    if ceiling is not None and company_id is not None:
        spent = uow.calls.credits_on_company(company_id)
        rate = uow.platform_settings.get()[0].credit_value_micro_usd
        if spent + credits_for(expected_cost, rate) > milli(ceiling):
            used = spent / 1000
            return f"budget per prospect reached ({used:g} of {ceiling} AI credits used)"
    return None
