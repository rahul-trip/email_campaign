"""What a workspace may do and how much of it is left (Phase 6d). Plain data and pure functions.

A **plan** sets limits per step, plus seats, mailboxes and features. A platform admin can then
**override** any of them for one customer, **grant** extra credits for a step, and set an
**access date**. What is left on a step is its limit plus the active grants, minus what this
period has used. The period is a month counted from the day the plan started.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from outbound.domain.enums import UsageStep, WorkspaceStatus

FEATURES = ("discovery", "directory_bypass", "follow_ups", "auto_send")

# Steps counted per lead, once; REWRITE is counted every time.
ONCE_PER_LEAD = frozenset(UsageStep) - {UsageStep.REWRITE}


@dataclass(frozen=True)
class Plan:
    """None for a limit means unlimited."""

    code: str
    name: str
    limits: Mapping[UsageStep, int | None] = field(default_factory=dict)  # missing: unlimited
    seats: int | None = 3
    mailboxes: int | None = 1
    active_campaigns: int | None = 2
    max_leads_per_run: int | None = None
    # The most a customer may set as "budget per prospect". Blank (no limit) is never allowed
    # on a platform-paid plan.
    max_prospect_budget_micro_usd: int | None = 500_000
    features: frozenset[str] = frozenset({"discovery"})
    access_days: int | None = 30  # how long a new customer's access lasts; None: no end


FREE = Plan("free", "Free", limits={UsageStep.DISCOVERY: 5, UsageStep.MANUAL: 5})

# For a workspace with no plan row (one that existed before plans did) and for the platform's own
# use: no limits, no end. Built in, not part of the editable catalog.
UNLIMITED = Plan(
    "unlimited",
    "Unlimited",
    seats=None,
    mailboxes=None,
    active_campaigns=None,
    max_prospect_budget_micro_usd=None,
    features=frozenset(FEATURES),
    access_days=None,
)


@dataclass(frozen=True)
class Override:
    """One setting changed for one customer. Keys: ``limit.<step>``, ``seats``, ``mailboxes``,
    ``active_campaigns``, ``max_leads_per_run``, ``max_prospect_budget``, ``feature.<name>``."""

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
    """Extra credits for one step."""

    step: UsageStep
    amount: int
    created_at: datetime
    expires_at: datetime | None = None  # None: never
    revoked_at: datetime | None = None
    note: str = ""
    id: str = ""

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True)
class Entitlements:
    limits: Mapping[UsageStep, int | None]
    seats: int | None
    mailboxes: int | None
    active_campaigns: int | None
    max_leads_per_run: int | None
    max_prospect_budget_micro_usd: int | None
    features: frozenset[str]

    def limit(self, step: UsageStep) -> int | None:
        return self.limits.get(step)

    def has(self, feature: str) -> bool:
        return feature in self.features


def effective_entitlements(
    plan: Plan, overrides: Iterable[Override], now: datetime
) -> Entitlements:
    """The plan with this customer's active overrides applied, the latest of a key winning."""
    limits = {step: plan.limits.get(step) for step in UsageStep}
    values: dict[str, int | None] = {
        "seats": plan.seats,
        "mailboxes": plan.mailboxes,
        "active_campaigns": plan.active_campaigns,
        "max_leads_per_run": plan.max_leads_per_run,
        "max_prospect_budget": plan.max_prospect_budget_micro_usd,
    }
    features = set(plan.features)
    for override in sorted((o for o in overrides if o.active(now)), key=lambda o: o.created_at):
        kind, _, name = override.key.partition(".")
        if kind == "limit" and name in {s.value for s in UsageStep}:
            limits[UsageStep(name)] = None if override.value is None else int(override.value)
        elif kind == "feature":
            if override.value:
                features.add(name)
            else:
                features.discard(name)
        elif override.key in values:
            values[override.key] = None if override.value is None else int(override.value)
    return Entitlements(
        limits=limits,
        seats=values["seats"],
        mailboxes=values["mailboxes"],
        active_campaigns=values["active_campaigns"],
        max_leads_per_run=values["max_leads_per_run"],
        max_prospect_budget_micro_usd=values["max_prospect_budget"],
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


def available(
    step: UsageStep,
    entitlements: Entitlements,
    grants: Iterable[Grant],
    used: int,
    now: datetime,
) -> int | None:
    """How many more of ``step`` may be used this period. None: no limit."""
    limit = entitlements.limit(step)
    if limit is None:
        return None
    extra = sum(g.amount for g in grants if g.step is step and g.active(now))
    return max(0, limit + extra - used)


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
class StepQuota:
    step: UsageStep
    limit: int | None  # after overrides; None: unlimited
    granted: int  # active grants
    used: int  # this period
    remaining: int | None  # None: unlimited


@dataclass(frozen=True)
class Quota:
    """Everything the guards and the Plan & usage page need about one workspace, at one moment."""

    plan: Plan
    entitlements: Entitlements
    steps: Mapping[UsageStep, StepQuota]
    period_start: datetime
    period_end: datetime
    access_until: datetime | None
    access: AccessLevel
    engine: bool  # the worker may work for it

    def remaining(self, step: UsageStep) -> int | None:
        return self.steps[step].remaining

    def has_credit(self, step: UsageStep) -> bool:
        left = self.steps[step].remaining
        return left is None or left > 0


def compute_quota(
    assignment: PlanAssignment,
    plan: Plan,
    overrides: Iterable[Override],
    grants: Iterable[Grant],
    used: Mapping[UsageStep, int],
    status: WorkspaceStatus,
    now: datetime,
) -> Quota:
    grants = list(grants)
    ent = effective_entitlements(plan, overrides, now)
    start, end = period_bounds(assignment.started_at, now)
    steps = {}
    for step in UsageStep:
        count = used.get(step, 0)
        steps[step] = StepQuota(
            step=step,
            limit=ent.limit(step),
            granted=sum(g.amount for g in grants if g.step is step and g.active(now)),
            used=count,
            remaining=available(step, ent, grants, count, now),
        )
    level = access_level(status, assignment.access_until, now)
    return Quota(
        plan=plan,
        entitlements=ent,
        steps=steps,
        period_start=start,
        period_end=end,
        access_until=assignment.access_until,
        access=level,
        engine=engine_may_run(status, level),
    )
