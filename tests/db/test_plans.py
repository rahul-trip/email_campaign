"""Plans, overrides, grants, usage and the platform settings (Phase 6d), at the database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entitlements import FREE, Plan, compute_quota
from outbound.domain.enums import CompanySource, UsageStep, WorkspaceStatus
from outbound.domain.platform_settings import PlatformSettings

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def around_now() -> tuple[datetime, datetime]:
    """A window that contains the moment the test ran (rows are stamped with the real clock)."""
    now = datetime.now(UTC)
    return now - timedelta(days=1), now + timedelta(days=1)


def lead(factory: UnitOfWorkFactory, ws: str, domain: str = "acme.com") -> str:
    with factory(ws) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL)
        uow.commit()
    return company.id


# ------------------------------------------------------------------ charging


def test_a_step_is_charged_once_per_lead(factory: UnitOfWorkFactory, ws: str) -> None:
    company = lead(factory, ws)
    with factory(ws) as uow:
        assert uow.usage.charge(UsageStep.RESEARCH, company) is True
        assert uow.usage.charge(UsageStep.RESEARCH, company) is False  # a retry costs nothing
        assert uow.usage.charge(UsageStep.COPY, company) is True  # another step is its own charge
        uow.commit()
    with factory(ws) as uow:
        assert uow.usage.charged(UsageStep.RESEARCH, company)
        assert uow.usage.used(*around_now()) == {UsageStep.RESEARCH: 1, UsageStep.COPY: 1}


def test_a_repeated_charge_does_not_undo_the_rest_of_the_transaction(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws)
    with factory(ws) as uow:
        uow.usage.charge(UsageStep.RESEARCH, company)
        uow.usage.charge(UsageStep.RESEARCH, company)  # conflicts, inside a savepoint
        assert uow.usage.charge(UsageStep.COPY, company)  # the transaction is still usable
        uow.commit()
    with factory(ws) as uow:
        assert uow.usage.charged(UsageStep.RESEARCH, company)
        assert uow.usage.charged(UsageStep.COPY, company)


def test_a_rewrite_is_charged_every_time(factory: UnitOfWorkFactory, ws: str) -> None:
    company = lead(factory, ws)
    with factory(ws) as uow:
        assert [uow.usage.charge(UsageStep.REWRITE, company) for _ in range(3)] == [True] * 3
        uow.commit()
    with factory(ws) as uow:
        assert uow.usage.used(*around_now()) == {UsageStep.REWRITE: 3}


def test_deleting_a_lead_does_not_give_its_credits_back(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    from outbound.services.privacy import PrivacyService

    company = lead(factory, ws)
    with factory(ws) as uow:
        uow.usage.charge(UsageStep.MANUAL, company)
        uow.commit()
    PrivacyService(factory, ws).delete_lead(company, confirm_domain="acme.com")
    with factory(ws) as uow:
        assert uow.usage.charged(UsageStep.MANUAL, company)  # the row survived the lead
        assert uow.usage.charge(UsageStep.MANUAL, company) is False


def test_use_is_counted_per_period_and_per_workspace(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    mine, theirs = lead(factory, ws), lead(factory, other_ws)
    with factory(ws) as uow:
        uow.usage.charge(UsageStep.MANUAL, mine)
        uow.commit()
    with factory(other_ws) as uow:
        uow.usage.charge(UsageStep.MANUAL, theirs)
        uow.commit()
    with factory(ws) as uow:
        now = datetime.now(UTC)
        assert uow.usage.used(now - timedelta(days=1), now + timedelta(days=1)) == {
            UsageStep.MANUAL: 1
        }
        assert uow.usage.used(now + timedelta(days=1), now + timedelta(days=30)) == {}


# ------------------------------------------------------------------ the platform's side


def test_a_platform_admin_sets_the_plan_overrides_and_grants_and_the_workspace_sees_them(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    until = NOW + timedelta(days=30)
    with platform() as p:
        p.plans.set_plan(ws, "free", started_at=START, access_until=until, note="pilot")
        manual = p.plans.add_override(ws, "limit.manual", 20, note="pilot", set_by="u1")
        p.plans.add_override(ws, "limit.discovery", None)  # unlimited is a value, not an absence
        grant = p.plans.add_grant(ws, UsageStep.MANUAL, 10, expires_at=until, granted_by="u1")
        p.commit()
    with factory(ws) as uow:
        assignment = uow.usage.assignment()
        overrides, grants = uow.usage.overrides(), uow.usage.grants()
    assert assignment is not None and (assignment.plan_code, assignment.access_until) == (
        "free",
        until,
    )
    assert {o.key: o.value for o in overrides} == {"limit.manual": 20, "limit.discovery": None}
    assert [(g.step, g.amount, g.id) for g in grants] == [(UsageStep.MANUAL, 10, grant.id)]
    quota = compute_quota(
        assignment, FREE, overrides, grants, {UsageStep.MANUAL: 12}, WorkspaceStatus.ACTIVE, NOW
    )
    assert quota.steps[UsageStep.MANUAL].remaining == 20 + 10 - 12
    assert quota.steps[UsageStep.DISCOVERY].remaining is None and manual.id


def test_withdrawing_an_override_or_grant_keeps_the_record(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    with platform() as p:
        p.plans.set_plan(ws, "free", started_at=START)
        override = p.plans.add_override(ws, "seats", 9)
        grant = p.plans.add_grant(ws, UsageStep.MANUAL, 5)
        p.plans.revoke_override(ws, override.id)
        p.plans.revoke_grant(ws, grant.id)
        p.commit()
    with factory(ws) as uow:
        assert uow.usage.overrides()[0].revoked_at is not None
        assert uow.usage.grants()[0].revoked_at is not None


def test_one_workspace_cannot_touch_anothers_grant(
    platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with platform() as p:
        grant = p.plans.add_grant(ws, UsageStep.MANUAL, 5)
        p.commit()
    with platform() as p, pytest.raises(NotFound):
        p.plans.revoke_grant(other_ws, grant.id)


def test_extending_access_changes_only_the_date(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    with platform() as p:
        p.plans.set_plan(ws, "free", started_at=START, access_until=NOW)
        later = p.plans.set_access_until(ws, NOW + timedelta(days=30))
        p.plans.set_plan(ws, "gold")  # changing plan keeps the anchor and the date
        p.commit()
    with factory(ws) as uow:
        found = uow.usage.assignment()
    assert found is not None and found.plan_code == "gold"
    assert found.started_at == START and found.access_until == later.access_until


# ------------------------------------------------------------------ the platform settings


def test_the_settings_default_to_the_free_plan_and_save_with_a_version_check(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    with platform() as p:
        settings, version = p.settings.get()
        assert version == 0 and settings.plan("anything") == FREE
        gold = Plan(
            "gold",
            "Gold",
            limits={UsageStep.MANUAL: 500},
            seats=None,
            features=frozenset({"discovery", "auto_send"}),
        )
        fresh = PlatformSettings(
            plans={"free": FREE, "gold": gold},
            default_plan="free",
            announcement="Maintenance Sunday",
        )
        assert p.settings.save(fresh, expected_version=0) == 1
        p.commit()
    with factory(ws) as uow:  # a workspace reads the catalog
        read, version = uow.platform_settings.get()
    assert version == 1 and read.announcement == "Maintenance Sunday"
    assert read.plan("gold").limits[UsageStep.MANUAL] == 500 and read.plan("gold").seats is None
    assert "auto_send" in read.plan("gold").features
    with platform() as p, pytest.raises(ConcurrencyConflict):
        p.settings.save(read, expected_version=0)  # someone else saved first
    with platform() as p:
        assert p.settings.save(read, expected_version=1) == 2


def test_a_removed_plan_falls_back_to_the_default() -> None:
    settings = PlatformSettings()
    assert settings.plan("gone") == FREE
