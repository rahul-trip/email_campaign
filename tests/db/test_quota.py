"""The quota a workspace sees (Phase 6d): read fresh each time, so an admin's change applies to
the very next step."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entitlements import AccessLevel
from outbound.domain.enums import CallOutcome, WorkspaceStatus
from outbound.domain.platform_settings import PlatformSettings
from outbound.services.quota import QuotaService
from outbound.services.workspaces import create_workspace

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def at(factory: UnitOfWorkFactory, ws: str, when: datetime = NOW) -> QuotaService:
    return QuotaService(factory, ws, now=lambda: when)


def use(factory: UnitOfWorkFactory, ws: str, credits: int) -> None:
    """Calls that used ``credits`` AI credits, now."""
    with factory(ws) as uow:
        uow.calls.record(
            provider="tavily", operation="search", request_hash="h", outcome=CallOutcome.HIT,
            cost_micro_usd=credits * 10_000, credits_milli=credits * 1000,
        )  # fmt: skip
        uow.commit()


def test_a_workspace_with_no_plan_row_is_unlimited_and_never_expires(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    quota = at(factory, ws).quota()
    assert quota.plan.code == "unlimited" and quota.access is AccessLevel.FULL and quota.engine
    assert quota.credits.remaining_milli is None and quota.has_credits()
    assert quota.entitlements.seats is None and quota.access_until is None


def test_a_new_workspace_gets_the_default_plan_for_thirty_days(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    created = create_workspace(factory, platform, "Globex Ltd")
    quota = QuotaService(factory, created.id).quota()
    assert quota.plan.code == "free"
    assert quota.credits.allowance == 100 and quota.credits.remaining_milli == 100_000
    assert quota.access_until is not None
    assert timedelta(days=29) < quota.access_until - datetime.now(UTC) <= timedelta(days=30)


def test_a_grant_an_override_and_use_change_what_is_left_at_once(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    service = QuotaService(factory, ws)
    use(factory, ws, 100)
    assert service.quota().credits.remaining_milli == 0
    assert not service.quota().has_credits()
    with platform() as p:
        p.plans.add_grant(ws, 500)
        p.commit()
    assert service.quota().credits.remaining_milli == 500_000  # no restart, no cache
    with platform() as p:
        p.plans.add_override(ws, "monthly_credits", 2000)
        p.commit()
    assert service.quota().credits.remaining_milli == 2_400_000  # 2000 + 500 - 100


def test_use_in_the_last_period_does_not_count_in_this_one(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    use(factory, ws, 60)
    assert QuotaService(factory, ws).quota().credits.remaining_milli == 40_000
    next_month = datetime.now(UTC) + timedelta(days=33)
    assert at(factory, ws, next_month).quota().credits.remaining_milli == 100_000  # fresh period


def test_access_ends_at_the_date_and_extending_it_reopens_the_workspace(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    after = datetime.now(UTC) + timedelta(days=31)
    assert at(factory, ws, after).quota().access is AccessLevel.READ_ONLY
    assert not at(factory, ws, after).quota().engine
    with platform() as p:
        p.plans.set_access_until(ws, after + timedelta(days=30))
        p.commit()
    assert at(factory, ws, after).quota().access is AccessLevel.FULL
    assert at(factory, ws, after).quota().engine


def test_a_suspended_workspace_is_locked_and_a_paused_one_does_not_run(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    with platform() as p:
        p.workspaces.set_status(ws, WorkspaceStatus.PAUSED)
        p.commit()
    paused = QuotaService(factory, ws).quota()
    assert paused.access is AccessLevel.FULL and not paused.engine
    with platform() as p:
        p.workspaces.set_status(ws, WorkspaceStatus.ACTIVE)
        p.workspaces.set_status(ws, WorkspaceStatus.SUSPENDED)
        p.commit()
    assert QuotaService(factory, ws).quota().access is AccessLevel.LOCKED


def test_the_platform_kill_switch_stops_every_engine(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    assert QuotaService(factory, ws).quota().engine
    with platform() as p:
        current, version = p.settings.get()
        p.settings.save(
            PlatformSettings(**{**current.__dict__, "kill_runs": True}), expected_version=version
        )
        p.commit()
    assert not QuotaService(factory, ws).quota().engine
