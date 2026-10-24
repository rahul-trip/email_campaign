"""The quota a workspace sees (Phase 6d): read fresh each time, so an admin's change applies to
the very next step."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entitlements import AccessLevel
from outbound.domain.enums import CompanySource, UsageStep, WorkspaceStatus
from outbound.domain.platform_settings import PlatformSettings
from outbound.services.quota import QuotaService
from outbound.services.workspaces import create_workspace

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def at(factory: UnitOfWorkFactory, ws: str, when: datetime = NOW) -> QuotaService:
    return QuotaService(factory, ws, now=lambda: when)


def test_a_workspace_with_no_plan_row_is_unlimited_and_never_expires(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    quota = at(factory, ws).quota()
    assert quota.plan.code == "unlimited" and quota.access is AccessLevel.FULL and quota.engine
    assert all(quota.remaining(step) is None for step in UsageStep)
    assert quota.entitlements.seats is None and quota.access_until is None


def test_a_new_workspace_gets_the_default_plan_for_thirty_days(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    created = create_workspace(factory, platform, "Globex Ltd")
    quota = QuotaService(factory, created.id).quota()
    assert quota.plan.code == "free"
    assert (quota.remaining(UsageStep.DISCOVERY), quota.remaining(UsageStep.MANUAL)) == (5, 5)
    assert quota.remaining(UsageStep.RESEARCH) is None
    assert quota.access_until is not None
    assert timedelta(days=29) < quota.access_until - datetime.now(UTC) <= timedelta(days=30)


def test_a_grant_an_override_and_use_change_what_is_left_at_once(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    service = QuotaService(factory, ws)
    with factory(ws) as uow:
        for n in range(5):
            company = uow.companies.create(domain=f"a{n}.com", source=CompanySource.MANUAL)
            uow.usage.charge(UsageStep.MANUAL, company.id)
        uow.commit()
    assert service.quota().remaining(UsageStep.MANUAL) == 0
    assert not service.quota().has_credit(UsageStep.MANUAL)
    with platform() as p:
        p.plans.add_grant(ws, UsageStep.MANUAL, 10)
        p.commit()
    assert service.quota().remaining(UsageStep.MANUAL) == 10  # no restart, no cache
    with platform() as p:
        p.plans.add_override(ws, "limit.manual", 7)
        p.commit()
    assert service.quota().remaining(UsageStep.MANUAL) == 12  # 7 + 10 - 5


def test_use_in_the_last_period_does_not_count_in_this_one(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    with factory(ws) as uow:
        company = uow.companies.create(domain="a.com", source=CompanySource.MANUAL)
        uow.usage.charge(UsageStep.MANUAL, company.id)
        uow.commit()
    next_month = datetime.now(UTC) + timedelta(days=33)
    assert at(factory, ws, next_month).quota().remaining(UsageStep.MANUAL) == 5  # a fresh period


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
