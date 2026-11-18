"""What a workspace may do and how many AI credits it has left (Phase 6d). Plain data and pure
functions.

A **plan** gives a number of AI credits a month, plus seats, mailboxes and features. Every vendor
and model call uses credits (``domain.credits``). A platform admin can **override** any setting
for one customer, **grant** extra credits and set an **access date**. What is left is the monthly
credits plus the active grants, minus what this period's calls used. The period is a month
counted from the day the plan started.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from outbound.domain.credits import milli
from outbound.domain.enums import UsageStep, WorkspaceStatus

FEATURES = ("discovery", "directory_bypass", "follow_ups", "auto_send")

# Activity counted per lead, once (``usage_events``); REWRITE is counted every time. These are
# counts for reports, not limits: only AI credits limit what a workspace does.
ONCE_PER_LEAD = frozenset(UsageStep) - {UsageStep.REWRITE}


@dataclass(frozen=True)
class Plan:
    """None for a number means unlimited."""

    code: str
    name: str
    monthly_credits: int | None = 100  # AI credits each period
    seats: int | None = 3
    mailboxes: int | None = 1
    active_campaigns: int | None = 2
    max_leads_per_run: int | None = None
    # The most a customer may set as "budget per prospect", in AI credits. Blank (no limit) is
    # never allowed on a platform-paid plan.
    max_prospect_budget_credits: int | None = 50
    features: frozenset[str] = frozenset({"discovery"})
    access_days: int | None = 30  # how long a new customer's access lasts; None: no end


FREE = Plan("free", "Free", monthly_credits=100, seats=1, mailboxes=1, active_campaigns=1)
STARTER = Plan(
    "starter",
    "Starter",
    monthly_credits=2_000,
    seats=3,
    mailboxes=2,
    active_campaigns=2,
    features=frozenset({"discovery", "directory_bypass"}),
    access_days=None,
)
PRO = Plan(
    "pro",
    "Pro",
    monthly_credits=10_000,
    seats=10,
    mailboxes=5,
    active_campaigns=5,
    max_prospect_budget_credits=100,
    features=frozenset({"discovery", "directory_bypass", "follow_ups"}),
    access_days=None,
)
DEFAULT_PLANS = (FREE, STARTER, PRO)

# For a workspace with no plan row (one that existed before plans did) and for the platform's own
# use: no limits, no end. Built in, not part of the editable catalog.
UNLIMITED = Plan(
    "unlimited",
    "Unlimited",
    monthly_credits=None,
    seats=None,
    mailboxes=None,
    active_campaigns=None,
    max_prospect_budget_credits=None,
    features=frozenset(FEATURES),
    access_days=None,
)

# What can be overridden for one customer, besides ``feature.<name>``.
OVERRIDE_KEYS = frozenset(
    {
        "monthly_credits",
        "seats",
        "mailboxes",
        "active_campaigns",
        "max_leads_per_run",
        "max_prospect_budget",
    }
)


@dataclass(frozen=True)
class Override:
    """One setting changed for one customer. Keys: ``OVERRIDE_KEYS`` and ``feature.<name>``."""

    key: str
    value: int | bool | None
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    note: str = ""
    id: str = ""

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True)
class Grant:
    """Extra AI credits, added to each period's allowance while the grant lasts. ``step`` is
    only set on grants made before credits were one pool (migration 0029)."""

    amount: int  # AI credits
    created_at: datetime
    expires_at: datetime | None = None  # None: never
    revoked_at: datetime | None = None
    note: str = ""
    id: str = ""
    step: UsageStep | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True)
class Entitlements:
    monthly_credits: int | None
    seats: int | None
    mailboxes: int | None
    active_campaigns: int | None
    max_leads_per_run: int | None
    max_prospect_budget_credits: int | None
    features: frozenset[str]

    def has(self, feature: str) -> bool:
        return feature in self.features


def effective_entitlements(
    plan: Plan, overrides: Iterable[Override], now: datetime
) -> Entitlements:
    """The plan with this customer's active overrides applied, the latest of a key winning."""
    values: dict[str, int | None] = {
        "monthly_credits": plan.monthly_credits,
        "seats": plan.seats,
        "mailboxes": plan.mailboxes,
        "active_campaigns": plan.active_campaigns,
        "max_leads_per_run": plan.max_leads_per_run,
        "max_prospect_budget": plan.max_prospect_budget_credits,
    }
    features = set(plan.features)
    for override in sorted((o for o in overrides if o.active(now)), key=lambda o: o.created_at):
        kind, _, name = override.key.partition(".")
        if kind == "feature":
            if override.value:
                features.add(name)
            else:
                features.discard(name)
        elif override.key in values:
            values[override.key] = None if override.value is None else int(override.value)
    return Entitlements(
        monthly_credits=values["monthly_credits"],
        seats=values["seats"],
        mailboxes=values["mailboxes"],
        active_campaigns=values["active_campaigns"],
        max_leads_per_run=values["max_leads_per_run"],
        max_prospect_budget_credits=values["max_prospect_budget"],
        features=frozenset(features),
    )


def add_months(anchor: datetime, months: int) -> datetime:
    """``anchor`` moved by whole months, a day past the end of a short month clamped to its last."""
    index = anchor.year * 12 + (anchor.month - 1) + months
    year, month0 = divmod(index, 12)
    day = min(anchor.day, calendar.monthrange(year, month0 + 1)[1])
    return anchor.replace(year=year, month=month0 + 1, day=day)


def period_bounds(anchor: datetime, now: datetime) -> tuple[datetime, datetime]:
    """The month containing ``now``, counted from ``anchor`` (the day the plan started): from
    its start (inclusive) to the next one (exclusive). Before the anchor: the first month."""
    months = max(0, (now.year - anchor.year) * 12 + (now.month - anchor.month))
    start = add_months(anchor, months)
    if start > now and months > 0:
        months -= 1
        start = add_months(anchor, months)
    return start, add_months(anchor, months + 1)


def granted_credits(grants: Iterable[Grant], now: datetime) -> int:
    """The AI credits the active grants add to this period."""
    return sum(g.amount for g in grants if g.active(now))


def available(
    entitlements: Entitlements, grants: Iterable[Grant], used_milli: int, now: datetime
) -> int | None:
    """Milli-credits left this period. None: no limit. Never below zero, although a step that
    started with credits left finishes, so ``used`` may pass the allowance a little."""
    monthly = entitlements.monthly_credits
    if monthly is None:
        return None
    return max(0, milli(monthly + granted_credits(grants, now)) - used_milli)


class AccessLevel(StrEnum):
    FULL = "full"
    READ_ONLY = "read_only"  # people can read and sign in; nothing is changed, the engine waits
    LOCKED = "locked"  # nobody uses it


def access_level(
    status: WorkspaceStatus, access_until: datetime | None, now: datetime
) -> AccessLevel:
    if status not in (WorkspaceStatus.ACTIVE, WorkspaceStatus.PAUSED):
        return AccessLevel.LOCKED  # suspended, pending deletion, deleted
    if access_until is not None and access_until <= now:
        return AccessLevel.READ_ONLY
    return AccessLevel.FULL


def engine_may_run(status: WorkspaceStatus, level: AccessLevel) -> bool:
    """Whether the worker may do work for this workspace: access is full and it is not paused."""
    return level is AccessLevel.FULL and status is WorkspaceStatus.ACTIVE


@dataclass(frozen=True)
class PlanAssignment:
    """Which plan a workspace is on, from when, and until when it may be used."""

    plan_code: str
    started_at: datetime
    access_until: datetime | None = None
    note: str = ""


@dataclass(frozen=True)
class CreditQuota:
    monthly: int | None  # AI credits a period, after overrides; None: unlimited
    granted: int  # AI credits from active grants
    used_milli: int  # this period
    remaining_milli: int | None  # None: unlimited

    @property
    def allowance(self) -> int | None:
        """Monthly credits plus grants; None: unlimited."""
        return None if self.monthly is None else self.monthly + self.granted


@dataclass(frozen=True)
class Quota:
    """Everything the guards and the Plan & usage page need about one workspace, at one moment."""

    plan: Plan
    entitlements: Entitlements
    credits: CreditQuota
    period_start: datetime
    period_end: datetime
    access_until: datetime | None
    access: AccessLevel
    engine: bool  # the worker may work for it

    def has_credits(self) -> bool:
        left = self.credits.remaining_milli
        return left is None or left > 0

    @property
    def near_limit(self) -> bool:
        """Four fifths or more of the allowance used."""
        allowance = self.credits.allowance
        if not allowance:
            return allowance == 0
        return self.credits.used_milli >= milli(allowance) * 0.8


def compute_quota(
    assignment: PlanAssignment,
    plan: Plan,
    overrides: Iterable[Override],
    grants: Iterable[Grant],
    used_milli: int,
    status: WorkspaceStatus,
    now: datetime,
) -> Quota:
    grants = list(grants)
    ent = effective_entitlements(plan, overrides, now)
    start, end = period_bounds(assignment.started_at, now)
    level = access_level(status, assignment.access_until, now)
    return Quota(
        plan=plan,
        entitlements=ent,
        credits=CreditQuota(
            monthly=ent.monthly_credits,
            granted=granted_credits(grants, now),
            used_milli=used_milli,
            remaining_milli=available(ent, grants, used_milli, now),
        ),
        period_start=start,
        period_end=end,
        access_until=assignment.access_until,
        access=level,
        engine=engine_may_run(status, level),
    )
