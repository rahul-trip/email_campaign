"""The entitlement rules (Phase 6d): overrides, grants, the monthly period and access."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from outbound.domain.entitlements import (
    FREE,
    AccessLevel,
    Grant,
    Override,
    Plan,
    access_level,
    add_months,
    available,
    effective_entitlements,
    engine_may_run,
    period_bounds,
)
from outbound.domain.enums import UsageStep, WorkspaceStatus

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=5)


def override(key: str, value: int | bool | None, **kw: object) -> Override:
    return Override(key, value, created_at=kw.pop("created_at", EARLIER), **kw)  # type: ignore[arg-type]


def grant(step: UsageStep, amount: int, **kw: object) -> Grant:
    return Grant(step, amount, created_at=kw.pop("created_at", EARLIER), **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ the plan and its overrides


def test_the_free_plan_limits_only_discovery_and_manual_leads() -> None:
    ent = effective_entitlements(FREE, [], NOW)
    assert (ent.limit(UsageStep.DISCOVERY), ent.limit(UsageStep.MANUAL)) == (5, 5)
    for step in (
        UsageStep.RESEARCH,
        UsageStep.EMAIL,
        UsageStep.COPY,
        UsageStep.DELIVER,
        UsageStep.REWRITE,
    ):
        assert ent.limit(step) is None
    assert (ent.seats, ent.mailboxes, ent.active_campaigns) == (3, 1, 2)
    assert ent.has("discovery") and not ent.has("directory_bypass")


def test_an_override_replaces_a_limit_and_none_means_unlimited() -> None:
    ent = effective_entitlements(
        FREE, [override("limit.manual", 20), override("limit.discovery", None)], NOW
    )
    assert ent.limit(UsageStep.MANUAL) == 20 and ent.limit(UsageStep.DISCOVERY) is None


def test_the_latest_override_of_a_key_wins() -> None:
    older = override("seats", 5, created_at=NOW - timedelta(days=3))
    newer = override("seats", 9, created_at=NOW - timedelta(days=1))
    assert effective_entitlements(FREE, [newer, older], NOW).seats == 9


def test_an_expired_or_revoked_override_no_longer_applies() -> None:
    expired = override("limit.manual", 50, expires_at=NOW - timedelta(seconds=1))
    revoked = override("limit.discovery", 50, revoked_at=NOW - timedelta(days=1))
    live = override("mailboxes", 4, expires_at=NOW + timedelta(days=1))
    ent = effective_entitlements(FREE, [expired, revoked, live], NOW)
    assert (ent.limit(UsageStep.MANUAL), ent.limit(UsageStep.DISCOVERY), ent.mailboxes) == (5, 5, 4)


def test_features_are_switched_on_and_off_per_customer() -> None:
    ent = effective_entitlements(
        FREE,
        [override("feature.directory_bypass", True), override("feature.discovery", False)],
        NOW,
    )
    assert ent.has("directory_bypass") and not ent.has("discovery")


def test_unknown_override_keys_are_ignored_not_trusted() -> None:
    ent = effective_entitlements(
        FREE, [override("limit.nonsense", 1), override("whatever", 7)], NOW
    )
    assert ent == effective_entitlements(FREE, [], NOW)


# ------------------------------------------------------------------ what is left on a step


def test_credits_left_are_the_limit_plus_active_grants_minus_use() -> None:
    ent = effective_entitlements(FREE, [], NOW)
    assert available(UsageStep.MANUAL, ent, [], 3, NOW) == 2
    assert available(UsageStep.MANUAL, ent, [], 5, NOW) == 0
    assert available(UsageStep.MANUAL, ent, [], 9, NOW) == 0  # never negative
    assert available(UsageStep.MANUAL, ent, [grant(UsageStep.MANUAL, 10)], 5, NOW) == 10


def test_a_grant_counts_only_while_active_and_only_for_its_step() -> None:
    ent = effective_entitlements(FREE, [], NOW)
    grants = [
        grant(UsageStep.MANUAL, 10, expires_at=NOW + timedelta(days=1)),  # to a date
        grant(UsageStep.MANUAL, 100, expires_at=NOW - timedelta(minutes=1)),  # ran out
        grant(UsageStep.MANUAL, 100, revoked_at=NOW - timedelta(days=1)),  # taken back
        grant(UsageStep.DISCOVERY, 100),  # another step
        grant(UsageStep.MANUAL, 1),  # never expires
    ]
    assert available(UsageStep.MANUAL, ent, grants, 0, NOW) == 5 + 10 + 1


def test_an_unlimited_step_has_no_number() -> None:
    ent = effective_entitlements(FREE, [], NOW)
    assert available(UsageStep.RESEARCH, ent, [], 10_000, NOW) is None


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
    plan = Plan("gold", "Gold", seats=None, mailboxes=None, access_days=None)
    ent = effective_entitlements(plan, [], NOW)
    assert ent.seats is None and all(ent.limit(s) is None for s in UsageStep)
