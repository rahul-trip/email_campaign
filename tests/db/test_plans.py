"""Plans, overrides, grants, usage and the platform settings (Phase 6d), at the database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entitlements import FREE, Plan, compute_quota
from outbound.domain.enums import CallOutcome, CompanySource, UsageStep, WorkspaceStatus
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


def call(
    factory: UnitOfWorkFactory, ws: str, credits_milli: int, company: str | None = None
) -> None:
    """One metered call that used ``credits_milli`` AI credits (thousandths)."""
    with factory(ws) as uow:
        uow.calls.record(
            provider="hunter", operation="find", request_hash="h", outcome=CallOutcome.HIT,
            cost_micro_usd=credits_milli * 10, credits_milli=credits_milli, company_id=company,
        )  # fmt: skip
        uow.commit()


# ------------------------------------------------------------------ AI credits used


def test_every_calls_ai_credits_are_added_up_for_the_period(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws)
    call(factory, ws, 2450, company)
    call(factory, ws, 110)  # a model call, not about a lead
    call(factory, ws, 0, company)  # a cache hit uses nothing
    with factory(ws) as uow:
        assert uow.usage.credits_used(*around_now()) == 2560
        assert uow.calls.credits_on_company(company) == 2450


def test_activity_is_still_counted_once_per_lead_for_reports(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws)
    with factory(ws) as uow:
        assert uow.usage.charge(UsageStep.RESEARCH, company) is True
        assert uow.usage.charge(UsageStep.RESEARCH, company) is False  # counted once
        assert [uow.usage.charge(UsageStep.REWRITE, company) for _ in range(2)] == [True, True]
        uow.commit()
    with factory(ws) as uow:
        assert uow.usage.charged(UsageStep.RESEARCH, company)
        assert uow.usage.credits_used(*around_now()) == 0  # counts are not credits


def test_deleting_a_lead_does_not_give_its_credits_back(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    from outbound.services.privacy import PrivacyService

    company = lead(factory, ws)
    call(factory, ws, 3000, company)
    PrivacyService(factory, ws).delete_lead(company, confirm_domain="acme.com")
    with factory(ws) as uow:
        assert uow.usage.credits_used(*around_now()) == 3000  # the ledger row survived the lead


def test_use_is_counted_per_period_and_per_workspace(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    call(factory, ws, 1000)
    call(factory, other_ws, 7000)
    with factory(ws) as uow:
        now = datetime.now(UTC)
        assert uow.usage.credits_used(now - timedelta(days=1), now + timedelta(days=1)) == 1000
        assert uow.usage.credits_used(now + timedelta(days=1), now + timedelta(days=30)) == 0


# ------------------------------------------------------------------ the platform's side


def test_a_platform_admin_sets_the_plan_overrides_and_grants_and_the_workspace_sees_them(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    until = NOW + timedelta(days=30)
    with platform() as p:
        p.plans.set_plan(ws, "free", started_at=START, access_until=until, note="pilot")
        monthly = p.plans.add_override(ws, "monthly_credits", 200, note="pilot", set_by="u1")
        p.plans.add_override(ws, "seats", None)  # unlimited is a value, not an absence
        grant = p.plans.add_grant(ws, 50, expires_at=until, granted_by="u1")
        p.commit()
    with factory(ws) as uow:
        assignment = uow.usage.assignment()
        overrides, grants = uow.usage.overrides(), uow.usage.grants()
    assert assignment is not None and (assignment.plan_code, assignment.access_until) == (
        "free",
        until,
    )
    assert {o.key: o.value for o in overrides} == {"monthly_credits": 200, "seats": None}
    assert [(g.step, g.amount, g.id) for g in grants] == [(None, 50, grant.id)]
    quota = compute_quota(assignment, FREE, overrides, grants, 12_000, WorkspaceStatus.ACTIVE, NOW)
    assert quota.credits.allowance == 250
    assert quota.credits.remaining_milli == (200 + 50 - 12) * 1000
    assert quota.entitlements.seats is None and monthly.id


def test_withdrawing_an_override_or_grant_keeps_the_record(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    with platform() as p:
        p.plans.set_plan(ws, "free", started_at=START)
        override = p.plans.add_override(ws, "seats", 9)
        grant = p.plans.add_grant(ws, 5)
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
        grant = p.plans.add_grant(ws, 5)
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
        assert sorted(settings.plans) == ["free", "pro", "starter"]
        gold = Plan(
            "gold",
            "Gold",
            monthly_credits=50_000,
            seats=None,
            features=frozenset({"discovery", "auto_send"}),
        )
        fresh = PlatformSettings(
            plans={"free": FREE, "gold": gold},
            default_plan="free",
            announcement="Maintenance Sunday",
            credit_value_micro_usd=20_000,
            vendor_caps={"hunter": 3000},
            llm_charges={"deepseek-v3": (30.0, 110.0)},
        )
        assert p.settings.save(fresh, expected_version=0) == 1
        p.commit()
    with factory(ws) as uow:  # a workspace reads the catalog
        read, version = uow.platform_settings.get()
    assert version == 1 and read.announcement == "Maintenance Sunday"
    assert read.plan("gold").monthly_credits == 50_000 and read.plan("gold").seats is None
    assert read.credit_value_micro_usd == 20_000 and read.vendor_caps == {"hunter": 3000}
    assert read.llm_charges == {"deepseek-v3": (30.0, 110.0)}
    assert "auto_send" in read.plan("gold").features
    with platform() as p, pytest.raises(ConcurrencyConflict):
        p.settings.save(read, expected_version=0)  # someone else saved first
    with platform() as p:
        assert p.settings.save(read, expected_version=1) == 2


def test_a_removed_plan_falls_back_to_the_default() -> None:
    settings = PlatformSettings()
    assert settings.plan("gone") == FREE


def test_settings_saved_before_ai_credits_are_read_in_credits() -> None:
    from outbound.domain.platform_settings import from_json

    old = from_json(
        {
            "plans": [{"code": "free", "name": "Free", "limits": {"manual": 5},
                       "max_prospect_budget_micro_usd": 500_000}],
            "vendor_caps": {"hunter": 20_000_000},
        }
    )  # fmt: skip
    assert old.plan("free").monthly_credits == 100  # the default for the plan
    assert old.plan("free").max_prospect_budget_credits == 50  # $0.50 at a cent a credit
    assert old.vendor_caps == {"hunter": 2000}  # $20 at a cent a credit
