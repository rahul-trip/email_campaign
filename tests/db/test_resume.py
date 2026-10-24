"""Work that waits for credits continues when credits exist (Phase 6d): by the tick, by a
person, oldest first and never beyond what the credits allow."""

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
from tests.db.test_credits import add, limit, started, status_of, used


def resume(factory: UnitOfWorkFactory, ws: str, pipeline: Pipeline) -> ResumeService:
    return ResumeService(factory, ws, pipeline.intake)


def grant(platform: PlatformUnitOfWorkFactory, ws: str, step: UsageStep, amount: int) -> None:
    with platform() as p:
        p.plans.add_grant(ws, step, amount)
        p.commit()


def waiting_domains(factory: UnitOfWorkFactory, ws: str) -> list[str]:
    with factory(ws) as uow:
        return [c.domain for c in uow.companies.waiting_for_credits()]


def test_the_tick_releases_waiting_leads_oldest_first_and_never_beyond_the_credits(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    limit(platform, ws, "research", 0)
    for domain in ("first.co.uk", "second.co.uk", "third.co.uk"):
        add(pipeline, domain)
        pipeline.runner.run_pipeline()  # each waits, in this order
    assert sorted(waiting_domains(factory, ws)) == ["first.co.uk", "second.co.uk", "third.co.uk"]
    assert resume(factory, ws, pipeline).run() == {"leads": 0, "rows": 0}  # no credit yet

    grant(platform, ws, UsageStep.RESEARCH, 2)
    assert resume(factory, ws, pipeline).run() == {"leads": 2, "rows": 0}
    assert waiting_domains(factory, ws) == ["third.co.uk"]  # the newest still waits
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "first.co.uk") == (CompanyStatus.COPY_READY, None)
    assert status_of(factory, ws, "second.co.uk") == (CompanyStatus.COPY_READY, None)
    assert status_of(factory, ws, "third.co.uk") == (CompanyStatus.NEW, UsageStep.RESEARCH)
    assert used(factory, ws)["research"] == 2


def test_a_tick_after_a_grant_resumes_and_runs_the_lead_in_the_same_pass(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    limit(platform, ws, "research", 0)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.NEW, UsageStep.RESEARCH)
    grant(platform, ws, UsageStep.RESEARCH, 1)
    report = pipeline.tick.run()
    assert report.jobs["credit_resume"] == {"leads": 1, "rows": 0}
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.COPY_READY, None)


def test_resume_by_hand_refuses_without_a_credit_and_says_when_credits_renew(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    limit(platform, ws, "research", 0)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    with factory(ws) as uow:
        company = uow.companies.waiting_for_credits()[0]
    service = resume(factory, ws, pipeline)
    with pytest.raises(NoCredits) as refused:
        service.resume_lead(company.id, actor="user:u1")
    assert refused.value.step is UsageStep.RESEARCH
    assert refused.value.renews > datetime.now(UTC)  # the date the allowance comes back
    with pytest.raises(NoCredits):
        service.release_all(actor="user:u1")
    assert waiting_domains(factory, ws) == ["acme.co.uk"]  # nothing was changed by the refusals

    grant(platform, ws, UsageStep.RESEARCH, 1)
    assert service.resume_lead(company.id, actor="user:u1") is UsageStep.RESEARCH
    assert waiting_domains(factory, ws) == []
    with pytest.raises(NoCredits, match="not waiting"):
        service.resume_lead(company.id, actor="user:u1")


def test_a_lead_that_already_paid_for_its_step_resumes_without_a_credit(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()  # researched, so charged for research
    with factory(ws) as uow:
        company = uow.companies.get(next(c.id for c in uow.companies.search()[0]))
        uow.companies.wait_for_credit(company.id, UsageStep.RESEARCH)  # parked for a step it paid
        uow.commit()
    limit(platform, ws, "research", 0)
    assert (
        resume(factory, ws, pipeline).resume_lead(company.id, actor="user:u1") is UsageStep.RESEARCH
    )


def test_waiting_manual_rows_come_in_with_the_leads(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, *(f"lead{n}.com" for n in range(7)))  # five fit, two wait as rows
    service = resume(factory, ws, pipeline)
    waiting_leads, waiting_rows = service.waiting()
    assert (sum(waiting_leads.values()), waiting_rows) == (0, 2)
    grant(platform, ws, UsageStep.MANUAL, 1)
    assert service.release_all(actor="user:u1").rows == 1
    assert service.waiting()[1] == 1


def test_a_workspace_that_may_not_run_releases_nothing_from_the_tick(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    limit(platform, ws, "research", 0)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    grant(platform, ws, UsageStep.RESEARCH, 1)
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
