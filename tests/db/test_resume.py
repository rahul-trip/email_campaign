"""Work that waits for AI credits continues when credits are back (Phase 6d): by the tick, by a
person, oldest first."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanyStatus, UsageStep
from outbound.pipeline import Pipeline
from outbound.services.resume import NoCredits, ResumeService
from outbound.worker import Worker
from tests.db.test_credits import add, grant, monthly, started, status_of


def resume(factory: UnitOfWorkFactory, ws: str, pipeline: Pipeline) -> ResumeService:
    return ResumeService(factory, ws, pipeline.intake)


def waiting_domains(factory: UnitOfWorkFactory, ws: str) -> list[str]:
    with factory(ws) as uow:
        return [c.domain for c in uow.companies.waiting_for_credits()]


def parked(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, *domains: str
) -> tuple[str, Pipeline]:
    """A workspace whose leads were added and then waited, oldest first, for AI credits."""
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, *domains)
    monthly(platform, ws, 0)
    pipeline.runner.run_pipeline()
    return ws, pipeline


def test_the_tick_releases_waiting_leads_once_credits_are_back(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline = parked(engine, factory, platform, "first.co.uk", "second.co.uk")
    assert sorted(waiting_domains(factory, ws)) == ["first.co.uk", "second.co.uk"]
    assert resume(factory, ws, pipeline).run() == {"leads": 0, "rows": 0}  # no credits yet

    grant(platform, ws, 1000)
    assert resume(factory, ws, pipeline).run() == {"leads": 2, "rows": 0}
    assert waiting_domains(factory, ws) == []
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "first.co.uk") == (CompanyStatus.COPY_READY, None)
    assert status_of(factory, ws, "second.co.uk") == (CompanyStatus.COPY_READY, None)


def test_a_lead_released_when_credits_are_short_waits_again_before_its_next_paid_stage(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline = parked(engine, factory, platform, "acme.co.uk")
    grant(platform, ws, 1)  # one credit: enough to start, not to finish
    resume(factory, ws, pipeline).run()
    pipeline.runner.run_pipeline()
    status, waiting_at = status_of(factory, ws, "acme.co.uk")
    assert status is not CompanyStatus.NEW and waiting_at is not None


def test_a_tick_after_a_grant_resumes_and_runs_the_lead_in_the_same_pass(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline = parked(engine, factory, platform, "acme.co.uk")
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.NEW, UsageStep.RESEARCH)
    grant(platform, ws, 1000)
    report = pipeline.tick.run()
    assert report.jobs["credit_resume"] == {"leads": 1, "rows": 0}
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.COPY_READY, None)


def test_resume_by_hand_refuses_without_credits_and_says_when_they_renew(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline = parked(engine, factory, platform, "acme.co.uk")
    with factory(ws) as uow:
        company = uow.companies.waiting_for_credits()[0]
    service = resume(factory, ws, pipeline)
    with pytest.raises(NoCredits, match="no AI credits left") as refused:
        service.resume_lead(company.id, actor="user:u1")
    assert refused.value.step is UsageStep.RESEARCH
    assert refused.value.renews > datetime.now(UTC)  # the date the credits come back
    with pytest.raises(NoCredits):
        service.release_all(actor="user:u1")
    assert waiting_domains(factory, ws) == ["acme.co.uk"]  # nothing was changed by the refusals

    grant(platform, ws, 100)
    assert service.resume_lead(company.id, actor="user:u1") is UsageStep.RESEARCH
    assert waiting_domains(factory, ws) == []
    with pytest.raises(NoCredits, match="not waiting"):
        service.resume_lead(company.id, actor="user:u1")


def test_waiting_manual_rows_come_in_with_the_leads(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    monthly(platform, ws, 0)
    add(pipeline, "lead0.com", "lead1.com")  # no credits: both wait as rows
    service = resume(factory, ws, pipeline)
    waiting_leads, waiting_rows = service.waiting()
    assert (sum(waiting_leads.values()), waiting_rows) == (0, 2)
    grant(platform, ws, 10)
    assert service.release_all(actor="user:u1").rows == 2
    assert service.waiting()[1] == 0


def test_a_workspace_that_may_not_run_releases_nothing_from_the_tick(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline = parked(engine, factory, platform, "acme.co.uk")
    grant(platform, ws, 100)
    with platform() as p:
        p.plans.set_access_until(ws, datetime.now(UTC) - timedelta(days=1))
        p.commit()
    assert resume(factory, ws, pipeline).run() == {"leads": 0, "rows": 0}
    with pytest.raises(NoCredits, match="access has ended"):
        resume(factory, ws, pipeline).release_all(actor="user:u1")


# ------------------------------------------------------------------ the scheduler


def test_the_scheduler_skips_workspaces_without_access_and_everyone_when_killed(
    engine: Engine,
    platform_engine: Engine,
    factory: UnitOfWorkFactory,
    platform: PlatformUnitOfWorkFactory,
) -> None:
    from outbound.domain.platform_settings import PlatformSettings
    from outbound.services.workspaces import create_workspace

    open_ws = create_workspace(factory, platform, "Open Ltd").id
    expired = create_workspace(factory, platform, "Expired Ltd").id
    with platform() as p:
        p.plans.set_access_until(expired, datetime.now(UTC) - timedelta(days=1))
        p.commit()
        assert set(p.scheduler.active_workspaces()) == {open_ws}
    container = container_for(Settings(_env_file=None), engine, platform_engine)
    worker = Worker(container, lambda ws: None, tick_every=timedelta(minutes=15))  # type: ignore[arg-type,return-value]
    assert [job.workspace_id for job in worker.plan()] == [open_ws]
    with platform() as p:
        current, version = p.settings.get()
        p.settings.save(
            PlatformSettings(**{**current.__dict__, "kill_runs": True}), expected_version=version
        )
        p.commit()
    assert worker.plan() == []  # the kill switch stops everyone
