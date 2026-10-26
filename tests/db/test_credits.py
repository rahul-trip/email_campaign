"""Charging and waiting in the pipeline (Phase 6d): a step is charged once per lead, a lead
without a credit waits where it is, and an admin's change applies to the next run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from outbound.providers.ports import SearchHit
from outbound.services.intake import WAITING_FOR_CREDITS
from outbound.services.leads import LeadService
from outbound.services.workspaces import create_workspace
from tests.stages.world import PROFILE, World


def started(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> tuple[str, Pipeline, World]:
    """A fresh workspace on the Free plan whose profile is confirmed, with a fake world."""
    ws = create_workspace(factory, platform, "Globex Ltd").id
    with factory(ws) as uow:
        uow.own_workspace.set_sender_profile({**PROFILE})
        [campaign] = uow.campaigns.all()
        uow.campaigns.update(
            campaign.id, {"target_titles": ["CTO"], "icp_description": "Utilities"}
        )
        uow.commit()
    world = World()
    pipeline = assemble(container_for(Settings(_env_file=None), engine), ws, world.providers())
    return ws, pipeline, world


def used(factory: UnitOfWorkFactory, ws: str) -> dict[str, int]:
    with factory(ws) as uow:
        now = datetime.now(UTC)
        return {
            s.value: n
            for s, n in uow.usage.used(now - timedelta(days=1), now + timedelta(days=1)).items()
        }


def add(pipeline: Pipeline, *domains: str) -> None:
    pipeline.intake.run(
        [{"Website": d, "Company": d.split(".")[0], "Country": "UK"} for d in domains]
    )


def limit(platform: PlatformUnitOfWorkFactory, ws: str, step: str, value: int | None) -> None:
    with platform() as p:
        p.plans.add_override(ws, f"limit.{step}", value)
        p.commit()


def status_of(
    factory: UnitOfWorkFactory, ws: str, domain: str
) -> tuple[CompanyStatus, UsageStep | None]:
    with factory(ws) as uow:
        company = next(c for c in uow.companies.search()[0] if c.domain == domain)
    return company.status, company.credit_wait_step


# ------------------------------------------------------------------ charging


def test_every_step_that_succeeds_is_charged_once(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    assert used(factory, ws) == {"manual": 1, "research": 1, "email": 1, "copy": 1}
    [queued] = pipeline.review.queue()
    pipeline.review.approve(queued.message.id)
    pipeline.runner.run_pipeline()
    assert used(factory, ws) == {"manual": 1, "research": 1, "email": 1, "copy": 1, "deliver": 1}


def test_research_again_and_reruns_cost_nothing_for_a_step_already_charged(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    LeadService(factory, ws).research_again(queued.company.id)
    pipeline.runner.run_pipeline()
    pipeline.runner.run_pipeline()  # a rerun with nothing due
    assert used(factory, ws) == {"manual": 1, "research": 1, "email": 1, "copy": 1}


# ------------------------------------------------------------------ waiting in place


def test_a_lead_without_a_credit_waits_where_it_is_and_the_rest_carry_on(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world = started(engine, factory, platform)
    limit(platform, ws, "research", 1)
    add(pipeline, "first.co.uk", "second.co.uk")
    report = pipeline.runner.run_pipeline()
    assert (
        report.count(
            "research", __import__("outbound.runner.runner", fromlist=["Outcome"]).Outcome.WAITING
        )
        == 1
    )
    states = [status_of(factory, ws, d) for d in ("first.co.uk", "second.co.uk")]
    assert (CompanyStatus.COPY_READY, None) in states  # one went all the way
    assert (CompanyStatus.NEW, UsageStep.RESEARCH) in states  # the other waits, still new
    assert world.search.extracted and used(factory, ws)["research"] == 1


def test_a_waiting_lead_is_not_picked_up_again_and_the_wait_is_recorded_once(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    limit(platform, ws, "research", 0)
    add(pipeline, "acme.co.uk")
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


def test_an_approved_email_survives_waiting_for_the_deliver_credit(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world = started(engine, factory, platform)
    limit(platform, ws, "deliver", 0)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    pipeline.review.approve(queued.message.id)
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.APPROVED, UsageStep.DELIVER)
    with factory(ws) as uow:
        assert uow.messages.get(queued.message.id).state is MessageState.APPROVED  # not withdrawn
    assert world.mailbox.appends == 0


def test_a_step_already_charged_on_a_lead_needs_no_credit_to_run_again(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    limit(platform, ws, "research", 0)  # the allowance is gone, but this lead already paid for it
    LeadService(factory, ws).research_again(queued.company.id)
    pipeline.runner.run_pipeline()
    assert status_of(factory, ws, "acme.co.uk") == (CompanyStatus.COPY_READY, None)


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


def test_the_sixth_manual_lead_in_a_month_waits_and_is_added_after_a_grant(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    statuses = rows(pipeline, *(f"lead{n}.com" for n in range(7)))
    assert statuses == [ImportRowStatus.ACCEPTED] * 5 + [ImportRowStatus.PENDING] * 2
    waiting = pipeline.intake.waiting_for_credits()
    assert [r.resolved_domain for r in waiting] == ["lead5.com", "lead6.com"]
    assert all(r.reason == WAITING_FOR_CREDITS for r in waiting)
    assert used(factory, ws)["manual"] == 5
    with factory(ws) as uow:
        assert {c.domain for c in uow.companies.search()[0]} == {f"lead{n}.com" for n in range(5)}

    assert pipeline.intake.release_waiting() == 0  # nothing to release without credits
    with platform() as p:
        p.plans.add_grant(ws, UsageStep.MANUAL, 1)
        p.commit()
    assert pipeline.intake.release_waiting() == 1  # one credit: the oldest row only
    assert [r.resolved_domain for r in pipeline.intake.waiting_for_credits()] == ["lead6.com"]
    with platform() as p:
        p.plans.add_grant(ws, UsageStep.MANUAL, 5)
        p.commit()
    assert pipeline.intake.release_waiting() == 1
    assert pipeline.intake.waiting_for_credits() == []
    assert used(factory, ws)["manual"] == 7


def test_merging_into_an_existing_lead_costs_no_credit(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    rows(pipeline, *(f"lead{n}.com" for n in range(5)))
    again = rows(pipeline, "lead0.com")  # already a lead: a merge, not a new one
    assert again == [ImportRowStatus.MERGED] and used(factory, ws)["manual"] == 5


def test_a_preview_charges_and_parks_nothing(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _ = started(engine, factory, platform)
    report = pipeline.intake.run(
        [{"Website": f"lead{n}.com"} for n in range(7)], validate_only=True
    )
    assert len(report.rows) == 7 and used(factory, ws) == {}


def test_discovery_adds_no_more_leads_than_credits_and_does_not_search_without_any(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    from outbound.pipeline import discover_companies

    ws, pipeline, world = started(engine, factory, platform)
    container = container_for(Settings(_env_file=None), engine)
    world.search.hits = [  # a search that has plenty to offer
        SearchHit(url=f"https://company{n}.com/about", title="About us", snippet="")
        for n in range(12)
    ]
    with platform() as p:
        p.plans.add_override(ws, "limit.discovery", 2)
        p.commit()
    assert discover_companies(pipeline, container, ws, "default", 10).added == 2  # not ten
    assert used(factory, ws)["discovery"] == 2
    searches = len(world.search.searches)
    assert discover_companies(pipeline, container, ws, "default", 10).added == 0  # none left
    assert len(world.search.searches) == searches  # and it did not even search


# ------------------------------------------------------------------ rewrites


def test_each_write_it_again_costs_a_rewrite_and_stops_when_none_are_left(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    import pytest

    from outbound.services.leads import LeadError

    ws, pipeline, _ = started(engine, factory, platform)
    limit(platform, ws, "rewrite", 1)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    leads = LeadService(factory, ws)
    leads.change_recipient(queued.company.id, queued.contact.id)  # write it again: 1 of 1
    pipeline.runner.run_pipeline()
    [again] = pipeline.review.queue()
    assert used(factory, ws)["rewrite"] == 1
    with pytest.raises(LeadError, match="no rewrite credits are left"):
        leads.change_recipient(again.company.id, again.contact.id)
    assert used(factory, ws)["rewrite"] == 1  # a refusal costs nothing
    with platform() as p:
        p.plans.add_grant(ws, UsageStep.REWRITE, 1)
        p.commit()
    leads.change_recipient(again.company.id, again.contact.id)
    assert used(factory, ws)["rewrite"] == 2


def test_asking_for_changes_is_refused_before_the_model_is_asked_when_none_are_left(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    import pytest

    from outbound.services.review import ReviewError, ReviewService

    ws, pipeline, world = started(engine, factory, platform)
    limit(platform, ws, "rewrite", 0)
    add(pipeline, "acme.co.uk")
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    calls = len(world.llm.calls) if hasattr(world.llm, "calls") else 0
    with pytest.raises(ReviewError, match="no rewrite credits are left"):
        ReviewService(factory, ws, world.llm).revise(queued.message.id, "shorter please")
    assert (len(world.llm.calls) if hasattr(world.llm, "calls") else 0) == calls  # no model call


def test_a_search_that_finds_only_known_companies_says_so_on_the_run(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    """The real complaint: Discover found the same top results every time, so nothing was added
    and the run looked empty. Known companies are skipped, and the run reports them."""
    from outbound.pipeline import discover_companies, execute_run
    from outbound.services.runs import RunMode, RunRequest

    ws, pipeline, world = started(engine, factory, platform)
    container = container_for(Settings(_env_file=None), engine)
    world.search.hits = [
        SearchHit(url=f"https://company{n}.com/about", title="About us", snippet="")
        for n in range(4)
    ]
    first = discover_companies(pipeline, container, ws, "default", 2)
    assert (first.added, first.already_leads) == (2, 0)
    # The same results come back: two are leads now, so the next two are taken instead.
    second = discover_companies(pipeline, container, ws, "default", 2)
    assert (second.added, second.already_leads) == (2, 2)
    third = discover_companies(pipeline, container, ws, "default", 1)
    # Nothing new: every search (the fake ignores the wording) returns the four known leads.
    assert third.added == 0 and third.already_leads == 4 * third.searches

    run = execute_run(pipeline, container, ws, RunRequest(mode=RunMode.DISCOVERY, discover=2))
    discovery = run.counts["discovery"]
    assert discovery["new leads"] == 0 and discovery["already leads"] == 4 * discovery["searches"]
