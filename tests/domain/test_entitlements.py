"""The entitlement rules (Phase 6d): AI credits, overrides, grants, the period and access."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from outbound.domain.credits import credits_for, llm_credits, milli
from outbound.domain.entitlements import (
    DEFAULT_PLANS,
    FREE,
    PRO,
    STARTER,
    UNLIMITED,
    AccessLevel,
    Grant,
    Override,
    Plan,
    PlanAssignment,
    access_level,
    add_months,
    available,
    compute_quota,
    effective_entitlements,
    engine_may_run,
    period_bounds,
)
from outbound.domain.enums import WorkspaceStatus

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=5)


def override(key: str, value: int | bool | None, **kw: object) -> Override:
    return Override(key, value, created_at=kw.pop("created_at", EARLIER), **kw)  # type: ignore[arg-type]


def grant(amount: int, **kw: object) -> Grant:
    return Grant(amount, created_at=kw.pop("created_at", EARLIER), **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ the plans


def test_there_are_three_plans_free_starter_and_pro_each_with_more_ai_credits() -> None:
    assert [p.code for p in DEFAULT_PLANS] == ["free", "starter", "pro"]
    assert FREE.monthly_credits < STARTER.monthly_credits < PRO.monthly_credits  # type: ignore[operator]
    assert FREE.access_days == 30 and STARTER.access_days is None and PRO.access_days is None
    assert UNLIMITED.monthly_credits is None


def test_the_free_plan_gives_ai_credits_seats_mailboxes_and_discovery() -> None:
    ent = effective_entitlements(FREE, [], NOW)
    assert ent.monthly_credits == 100
    assert (ent.seats, ent.mailboxes, ent.active_campaigns) == (1, 1, 1)
    assert ent.has("discovery") and not ent.has("directory_bypass")


def test_an_override_replaces_the_monthly_credits_and_none_means_unlimited() -> None:
    assert (
        effective_entitlements(FREE, [override("monthly_credits", 500)], NOW).monthly_credits == 500
    )
    assert (
        effective_entitlements(FREE, [override("monthly_credits", None)], NOW).monthly_credits
        is None
    )


def test_the_latest_override_of_a_key_wins() -> None:
    older = override("seats", 5, created_at=NOW - timedelta(days=3))
    newer = override("seats", 9, created_at=NOW - timedelta(days=1))
    assert effective_entitlements(FREE, [newer, older], NOW).seats == 9


def test_an_expired_or_revoked_override_no_longer_applies() -> None:
    expired = override("monthly_credits", 50, expires_at=NOW - timedelta(seconds=1))
    revoked = override("seats", 50, revoked_at=NOW - timedelta(days=1))
    live = override("mailboxes", 4, expires_at=NOW + timedelta(days=1))
    ent = effective_entitlements(FREE, [expired, revoked, live], NOW)
    assert (ent.monthly_credits, ent.seats, ent.mailboxes) == (100, 1, 4)


def test_features_are_switched_on_and_off_per_customer() -> None:
    ent = effective_entitlements(
        FREE,
        [override("feature.directory_bypass", True), override("feature.discovery", False)],
        NOW,
    )
    assert ent.has("directory_bypass") and not ent.has("discovery")


def test_unknown_and_old_per_step_override_keys_are_ignored_not_trusted() -> None:
    ent = effective_entitlements(FREE, [override("limit.manual", 1), override("whatever", 7)], NOW)
    assert ent == effective_entitlements(FREE, [], NOW)


# ------------------------------------------------------------------ AI credits left


def test_credits_left_are_the_monthly_credits_plus_active_grants_minus_use() -> None:
    ent = effective_entitlements(FREE, [], NOW)
    assert available(ent, [], milli(30), NOW) == milli(70)
    assert available(ent, [], milli(100), NOW) == 0
    assert available(ent, [], milli(130), NOW) == 0  # a finished step may overdraw; never negative
    assert available(ent, [grant(500)], milli(100), NOW) == milli(500)


def test_a_grant_counts_only_while_active() -> None:
    ent = effective_entitlements(FREE, [], NOW)
    grants = [
        grant(10, expires_at=NOW + timedelta(days=1)),  # to a date
        grant(100, expires_at=NOW - timedelta(minutes=1)),  # ran out
        grant(100, revoked_at=NOW - timedelta(days=1)),  # taken back
        grant(1),  # never expires
    ]
    assert available(ent, grants, 0, NOW) == milli(100 + 10 + 1)


def test_an_unlimited_plan_has_no_number() -> None:
    ent = effective_entitlements(UNLIMITED, [], NOW)
    assert available(ent, [], milli(1_000_000), NOW) is None


def test_the_quota_says_whether_credits_are_left_and_when_it_is_near_the_end() -> None:
    assignment = PlanAssignment("free", EARLIER)
    fresh = compute_quota(assignment, FREE, [], [], 0, WorkspaceStatus.ACTIVE, NOW)
    assert fresh.has_credits() and not fresh.near_limit
    assert fresh.credits.allowance == 100 and fresh.credits.remaining_milli == milli(100)
    near = compute_quota(assignment, FREE, [], [], milli(85), WorkspaceStatus.ACTIVE, NOW)
    assert near.has_credits() and near.near_limit
    spent = compute_quota(
        assignment, FREE, [], [grant(20)], milli(120), WorkspaceStatus.ACTIVE, NOW
    )
    assert not spent.has_credits() and spent.credits.allowance == 120
    endless = compute_quota(
        assignment, UNLIMITED, [], [], milli(10**6), WorkspaceStatus.ACTIVE, NOW
    )
    assert endless.has_credits() and not endless.near_limit


# ------------------------------------------------------------------ converting cost to AI credits


def test_a_calls_cost_becomes_ai_credits_at_the_platforms_rate_rounded_up() -> None:
    cent = 10_000  # micro-USD: the default value of one AI credit
    assert credits_for(0, cent) == 0  # a free call, a cache hit, an error
    assert credits_for(cent, cent) == 1000  # one credit, in thousandths
    assert credits_for(24_500, cent) == 2450  # a Hunter find: 2.45 credits
    assert credits_for(1, cent) == 1  # a paid call never costs nothing
    assert credits_for(24_500, 2 * cent) == 1225  # a credit worth more: fewer credits


def test_a_model_call_uses_the_charge_per_million_tokens_rounded_up() -> None:
    assert llm_credits(1_000_000, 0, 30, 100) == milli(30)
    assert llm_credits(0, 1_000_000, 30, 100) == milli(100)
    assert llm_credits(2_000, 500, 30, 100) == 110  # 0.06 + 0.05 credits
    assert llm_credits(1, 0, 30, 100) == 1  # never rounded down to nothing
    assert llm_credits(5_000, 5_000, 0, 0) == 0  # a free model


# ------------------------------------------------------------------ the monthly period


def test_the_period_is_a_month_from_the_day_the_plan_started() -> None:
    anchor = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
    assert period_bounds(anchor, datetime(2026, 10, 2, 9, 30, tzinfo=UTC)) == (
        anchor, datetime(2026, 11, 2, 9, 30, tzinfo=UTC),
    )  # fmt: skip
    assert period_bounds(anchor, datetime(2026, 11, 2, 9, 29, tzinfo=UTC))[0] == anchor
    assert period_bounds(anchor, datetime(2026, 11, 2, 9, 30, tzinfo=UTC))[0] == datetime(
        2026, 11, 2, 9, 30, tzinfo=UTC
    )
    assert period_bounds(anchor, datetime(2027, 3, 1, tzinfo=UTC)) == (
        datetime(2027, 2, 2, 9, 30, tzinfo=UTC), datetime(2027, 3, 2, 9, 30, tzinfo=UTC),
    )  # fmt: skip


def test_a_period_starting_on_the_31st_never_drifts() -> None:
    anchor = datetime(2026, 1, 31, tzinfo=UTC)
    assert add_months(anchor, 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert add_months(anchor, 2) == datetime(2026, 3, 31, tzinfo=UTC)  # back on the 31st
    assert period_bounds(anchor, datetime(2026, 3, 15, tzinfo=UTC))[0] == datetime(
        2026, 2, 28, tzinfo=UTC
    )


def test_before_the_anchor_it_is_the_first_period() -> None:
    anchor = datetime(2026, 10, 2, tzinfo=UTC)
    assert period_bounds(anchor, anchor - timedelta(days=3)) == (
        anchor,
        datetime(2026, 11, 2, tzinfo=UTC),
    )


# ------------------------------------------------------------------ access


@pytest.mark.parametrize(
    ("status", "until", "level", "engine"),
    [
        (WorkspaceStatus.ACTIVE, None, AccessLevel.FULL, True),
        (WorkspaceStatus.ACTIVE, NOW + timedelta(days=1), AccessLevel.FULL, True),
        (WorkspaceStatus.ACTIVE, NOW, AccessLevel.READ_ONLY, False),  # the end is exclusive
        (WorkspaceStatus.ACTIVE, NOW - timedelta(days=1), AccessLevel.READ_ONLY, False),
        (WorkspaceStatus.PAUSED, None, AccessLevel.FULL, False),  # people work; the engine waits
        (WorkspaceStatus.PAUSED, NOW - timedelta(days=1), AccessLevel.READ_ONLY, False),
        (WorkspaceStatus.SUSPENDED, None, AccessLevel.LOCKED, False),
        (WorkspaceStatus.PENDING_DELETION, None, AccessLevel.LOCKED, False),
        (WorkspaceStatus.DELETED, NOW + timedelta(days=9), AccessLevel.LOCKED, False),
    ],
)
def test_access_for_every_combination(
    status: WorkspaceStatus, until: datetime | None, level: AccessLevel, engine: bool
) -> None:
    assert access_level(status, until, NOW) is level
    assert engine_may_run(status, level) is engine


def test_a_custom_plan_can_have_no_limits_and_no_end() -> None:
    plan = Plan("gold", "Gold", monthly_credits=None, seats=None, mailboxes=None, access_days=None)
    ent = effective_entitlements(plan, [], NOW)
    assert ent.seats is None and ent.monthly_credits is None
