"""AI credits in the pipeline (Phase 6d): every vendor and model call uses them, a lead waits
where it is when none are left, and an admin's change applies to the next run."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanyStatus,
    EntityType,
    ImportRowStatus,
    MessageState,
    UsageStep,
)
from outbound.pipeline import Pipeline, assemble
from outbound.providers.ports import CompanyMention
from outbound.runner.runner import Outcome
from outbound.services.intake import WAITING_FOR_CREDITS
from outbound.services.leads import LeadService
from outbound.services.resume import ResumeService
from outbound.services.workspaces import create_workspace
from tests.stages.world import PROFILE, World

FINDER_PRICE = 50_000  # micro-USD: five AI credits at the default rate
MODEL_CHARGE = (100.0, 500.0)  # AI credits per million tokens in and out
# The fake model reports 1,000 tokens in and 200 out: 0.1 + 0.1 credits a call.
MODEL_CALL = 200


def started(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> tuple[str, Pipeline, World]:
    """A fresh workspace on the Free plan whose profile is confirmed, with a fake world whose
    finder has a price and whose model has a charge."""
    ws = create_workspace(factory, platform, "Globex Ltd").id
    with factory(ws) as uow:
        uow.own_workspace.set_sender_profile({**PROFILE})
        [campaign] = uow.campaigns.all()
        uow.campaigns.update(
            campaign.id, {"target_titles": ["CTO"], "icp_description": "Utilities"}
        )
        uow.commit()
    with platform() as p:
        current, version = p.settings.get()
        charges = {"fake-model": MODEL_CHARGE}
        p.settings.save(replace(current, llm_charges=charges), expected_version=version)
        p.commit()
    world = World()
    settings = Settings(_env_file=None, provider_prices={"finder:find": FINDER_PRICE})
    pipeline = assemble(container_for(settings, engine), ws, world.providers())
    return ws, pipeline, world


def window() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now - timedelta(days=1), now + timedelta(days=1)


def used(factory: UnitOfWorkFactory, ws: str) -> int:
    """AI credits used, in thousandths."""
    with factory(ws) as uow:
        return uow.usage.credits_used(*window())


def counted(factory: UnitOfWorkFactory, ws: str) -> dict[str, int]:
    """Steps counted for reports (not credits)."""
    from sqlalchemy import func, select

    from outbound.db.models import UsageEventRow

    with factory(ws) as uow:
        rows = uow.session.execute(
            select(UsageEventRow.step, func.count())
            .where(UsageEventRow.workspace_id == ws)
            .group_by(UsageEventRow.step)
        )
        return {step.value: int(n) for step, n in rows}


def add(pipeline: Pipeline, *domains: str) -> None:
    pipeline.intake.run(
        [{"Website": d, "Company": d.split(".")[0], "Country": "UK"} for d in domains]
    )


def monthly(platform: PlatformUnitOfWorkFactory, ws: str, credits: int | None) -> None:
    with platform() as p:
        p.plans.add_override(ws, "monthly_credits", credits)
        p.commit()


def grant(platform: PlatformUnitOfWorkFactory, ws: str, credits: int) -> None:
    with platform() as p:
        p.plans.add_grant(ws, credits)
        p.commit()


def status_of(
    factory: UnitOfWorkFactory, ws: str, domain: str
) -> tuple[CompanyStatus, UsageStep | None]:
    with factory(ws) as uow:
        company = next(c for c in uow.companies.search()[0] if c.domain == domain)
    return company.status, company.credit_wait_step


# ------------------------------------------------------------------ what uses AI credits


def test_every_paid_vendor_call_and_every_model_call_uses_ai_credits(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _world = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    with factory(ws) as uow:
        company = uow.companies.search()[0][0]
        calls = uow.calls.for_company(company.id)
    by_kind = {(c.provider, c.operation): c.credits_milli for c in calls}
    assert by_kind[("finder", "find")] == 5000  # its dollar price, at a cent a credit
    model_calls = [c for c in calls if c.provider == "fake-llm"]
    assert model_calls and all(c.credits_milli == MODEL_CALL for c in model_calls)
    assert all(c.credits_milli == 0 for c in calls if c.provider == "fake-search")  # unpriced
    assert used(factory, ws) == sum(c.credits_milli for c in calls)
    assert counted(factory, ws) == {"manual": 1, "research": 1, "email": 1, "copy": 1}


def test_a_model_with_no_charge_set_uses_no_credits_and_a_new_charge_applies_from_then_on(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    with platform() as p:
        current, version = p.settings.get()
        p.settings.save(replace(current, llm_charges={}), expected_version=version)
        p.commit()
    add(pipeline, "first.co.uk")
    pipeline.runner.run_pipeline()
    before = used(factory, ws)
    assert before == 5000  # only the finder
    with platform() as p:
        current, version = p.settings.get()
        charges = {"fake-model": MODEL_CHARGE}
        p.settings.save(replace(current, llm_charges=charges), expected_version=version)
        p.commit()
    assert used(factory, ws) == before  # calls already made keep what they used
    add(pipeline, "second.co.uk")
    pipeline.runner.run_pipeline()
    assert used(factory, ws) > before + 5000


def test_research_again_reuses_stored_answers_without_using_credits_for_them(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    first = used(factory, ws)
    pipeline.runner.run_pipeline()  # a rerun with nothing due uses nothing
    assert used(factory, ws) == first
    LeadService(factory, ws).research_again(queued.company.id)
    pipeline.runner.run_pipeline()
    with factory(ws) as uow:
        finder = [c for c in uow.calls.for_company(queued.company.id) if c.provider == "finder"]
    assert sum(c.credits_milli for c in finder) == 5000  # the address was not paid for twice


# ------------------------------------------------------------------ waiting in place


def test_a_lead_waits_where_it_is_when_no_credits_are_left_and_goes_on_after_a_grant(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")  # added while credits are left
    monthly(platform, ws, 0)
    report = pipeline.runner.run_pipeline()
    assert report.count("research", Outcome.WAITING) == 1
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.NEW, UsageStep.RESEARCH)
    assert not world.search.extracted and used(factory, ws) == 0
    grant(platform, ws, 100)
    ResumeService(factory, ws, pipeline.intake).release_all(actor="test")
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.COPY_READY, None)


def test_a_step_that_started_with_credits_left_finishes_even_past_the_allowance(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    monthly(platform, ws, 1)  # one credit: less than the email step's finder call alone
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    _state, waiting_at = status_of(factory, ws, "acme.co.uk")
    assert waiting_at is not None  # it stopped before a later paid stage
    assert used(factory, ws) > 1000  # the stage that started was allowed to finish


def test_a_waiting_lead_is_not_picked_up_again_and_the_wait_is_recorded_once(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    monthly(platform, ws, 0)
    pipeline.runner.run_pipeline()
    pipeline.runner.run_pipeline()
    pipeline.runner.run_pipeline()
    with factory(ws) as uow:
        company = uow.companies.search()[0][0]
        waits = [
            e
            for e in uow.events.for_entity(EntityType.COMPANY, company.id)
            if e.type == "waiting_for_credits"
        ]
        assert uow.companies.due(CompanyStatus.NEW, 10) == []  # parked
    assert len(waits) == 1 and waits[0].data == {"step": "research"}


def test_an_approved_email_is_saved_to_the_mailbox_with_no_credits_left(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    monthly(platform, ws, 0)  # saving a draft calls no vendor and no model
    pipeline.review.approve(queued.message.id)
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.IN_SEQUENCE, None)
    with factory(ws) as uow:
        assert uow.messages.get(queued.message.id).state is not MessageState.APPROVED
    assert world.mailbox.appends == 1


# ------------------------------------------------------------------ access and the kill switch


def test_a_workspace_past_its_access_date_does_no_work_and_continues_when_extended(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    with platform() as p:
        p.plans.set_access_until(ws, datetime.now(UTC) - timedelta(days=1))
        p.commit()
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.NEW, None)  # nothing lost
    assert not world.search.extracted
    with platform() as p:
        p.plans.set_access_until(ws, datetime.now(UTC) + timedelta(days=30))
        p.commit()
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.COPY_READY, None)


# --------------------------------------------------------------- intake: manual and discovered


def rows(pipeline: Pipeline, *domains: str) -> list[ImportRowStatus]:
    report = pipeline.intake.run([{"Website": d, "Company": d.split(".")[0]} for d in domains])
    return [r.status for r in report.rows]


def test_rows_added_with_no_credits_left_wait_and_are_added_after_a_grant(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    assert rows(pipeline, "lead0.com") == [ImportRowStatus.ACCEPTED]  # adding uses no credits
    monthly(platform, ws, 0)
    assert rows(pipeline, "lead1.com", "lead2.com") == [ImportRowStatus.PENDING] * 2
    waiting = pipeline.intake.waiting_for_credits()
    assert [r.resolved_domain for r in waiting] == ["lead1.com", "lead2.com"]
    assert all(r.reason == WAITING_FOR_CREDITS for r in waiting)
    assert pipeline.intake.release_waiting() == 0  # nothing to release without credits
    grant(platform, ws, 10)
    assert pipeline.intake.release_waiting() == 2
    assert pipeline.intake.waiting_for_credits() == []
    with factory(ws) as uow:
        assert {c.domain for c in uow.companies.search()[0]} == {f"lead{n}.com" for n in range(3)}


def test_merging_into_an_existing_lead_uses_no_credits(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    rows(pipeline, "lead0.com")
    assert rows(pipeline, "lead0.com") == [ImportRowStatus.MERGED]
    assert used(factory, ws) == 0 and counted(factory, ws) == {"manual": 1}


def test_a_preview_uses_and_parks_nothing(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    report = pipeline.intake.run(
        [{"Website": f"lead{n}.com"} for n in range(7)], validate_only=True
    )
    assert len(report.rows) == 7 and used(factory, ws) == 0 and counted(factory, ws) == {}


def test_discovery_does_not_search_without_ai_credits(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    from outbound.pipeline import discover_companies

    ws, pipeline, world = started(engine, factory, platform)
    container = container_for(Settings(_env_file=None), engine)
    world.directory.mentions = [
        CompanyMention(name=f"Grid {n}", domain=f"company{n}.com", source="yc_directory")
        for n in range(12)
    ]
    assert discover_companies(pipeline, container, ws, "default", 2).added == 2
    monthly(platform, ws, 0)
    asked = len(world.directory.queries), len(world.search.searches)
    assert discover_companies(pipeline, container, ws, "default", 10).added == 0
    assert (len(world.directory.queries), len(world.search.searches)) == asked  # nor looked


# ------------------------------------------------------------------ rewrites


def test_write_it_again_uses_model_credits_and_is_refused_when_none_are_left(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    from outbound.services.leads import LeadError

    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    leads = LeadService(factory, ws)
    leads.change_recipient(queued.company.id, queued.contact.id)
    before = used(factory, ws)
    pipeline.runner.run_pipeline()  # it is written again by the model
    [again] = pipeline.review.queue()
    assert used(factory, ws) > before
    monthly(platform, ws, 0)
    with pytest.raises(LeadError, match="no AI credits are left"):
        leads.change_recipient(again.company.id, again.contact.id)
    grant(platform, ws, 1000)
    leads.change_recipient(again.company.id, again.contact.id)


def test_asking_for_changes_is_refused_before_the_model_is_asked_when_none_are_left(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    from outbound.services.review import ReviewError, ReviewService

    ws, pipeline, world = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    monthly(platform, ws, 0)
    calls = len(world.llm.calls)
    with pytest.raises(ReviewError, match="no AI credits are left"):
        ReviewService(factory, ws, world.llm).revise(queued.message.id, "shorter please")
    assert len(world.llm.calls) == calls  # no model call


def test_a_search_that_finds_only_known_companies_says_so_on_the_run(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    """The real complaint: Discover found the same top results every time, so nothing was added
    and the run looked empty. Known companies are skipped, and the run reports them."""
    from outbound.pipeline import discover_companies, execute_run
    from outbound.services.runs import RunMode, RunRequest

    ws, pipeline, world = started(engine, factory, platform)
    container = container_for(Settings(_env_file=None), engine)
    # A lead added by hand that the directory also lists.
    add(pipeline, "company0.com")
    world.directory.mentions = [
        CompanyMention(name=f"Grid {n}", domain=f"company{n}.com", source="yc_directory")
        for n in range(3)
    ]
    first = discover_companies(pipeline, container, ws, "default", 1)
    assert (first.added, first.already_leads) == (1, 1)
    # The rest come back next time: one more is added, nothing is screened twice.
    second = discover_companies(pipeline, container, ws, "default", 5)
    assert second.added == 1 and second.found == 0
    third = discover_companies(pipeline, container, ws, "default", 1)
    assert third.added == 0  # nothing new anywhere

    run = execute_run(pipeline, container, ws, RunRequest(mode=RunMode.DISCOVERY, discover=2))
    assert run.counts["discovery"]["new leads"] == 0
