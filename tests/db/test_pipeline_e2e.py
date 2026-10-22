"""The whole engine with fake vendors: from a targets list to a mailbox draft and a Sent match.

This is the Phase 2 gate in miniature. It runs the real stages, runner, meter and database, and
replaces only the outside world (search, model, finders, verifier, mailbox).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select

from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.db.models import ProviderCallRow, WorkspaceRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CallOutcome,
    CompanyStatus,
    HoldReason,
    ImportRowStatus,
    MessageState,
)
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.pipeline import Pipeline, Providers, assemble
from outbound.providers.ports import (
    PageText,
    SentMessage,
)
from outbound.runner.runner import Outcome
from outbound.services.reports import ReportService
from outbound.services.runs import RunService
from tests.stages.fakes import FakeLlm
from tests.stages.world import PROFILE, SiteSearch, World

C = CompanyStatus


def build(
    engine: Engine,
    factory: UnitOfWorkFactory,
    ws: str,
    world: World,
    *,
    providers: Providers | None = None,
) -> tuple[Pipeline, Container]:
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        row = uow.session.get(WorkspaceRow, ws)
        assert row is not None
        row.sender_profile = PROFILE
        uow.campaigns.create(
            "default", ["CTO", "VP of Sales"], icp_description="Utilities that need forecasts"
        )
        uow.commit()
    container = Container(Settings(_env_file=None), engine, factory)
    return assemble(container, ws, providers or world.providers()), container


def paid_calls(factory: UnitOfWorkFactory, ws: str) -> int:
    with factory(ws) as uow:
        outcomes = [r.outcome for r in uow.session.scalars(select(ProviderCallRow))]
    return sum(o in (CallOutcome.HIT, CallOutcome.MISS) for o in outcomes)


def statuses(factory: UnitOfWorkFactory, ws: str) -> dict[str, CompanyStatus]:
    with factory(ws) as uow:
        return {
            domain: uow.companies.by_domain(domain).status  # type: ignore[union-attr]
            for domain in sorted(uow.companies.known_domains())
        }


ROWS = [
    {"Website": "acme.co.uk", "Company": "Acme Energy", "Country": "UK"},
    {"Website": "beta.com", "Company": "Beta Power", "Country": "US", "Notes": "met at the expo"},
]


def test_a_targets_list_becomes_drafts_and_a_rerun_costs_nothing(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    pipeline, _ = build(engine, factory, ws, world)

    # 1. intake
    report = pipeline.intake.run(ROWS)
    assert [r.status for r in report.rows] == [ImportRowStatus.ACCEPTED] * 2

    # 2. the engine runs every stage up to the human
    run = pipeline.runner.run_pipeline()
    assert statuses(factory, ws) == {"acme.co.uk": C.COPY_READY, "beta.com": C.COPY_READY}
    assert run.count("copy", Outcome.ADVANCED) == 2
    assert run.cost_micro_usd >= 0
    assert world.mailbox.appends == 0  # nothing reaches the mailbox without approval

    # 3. the operator reviews: approves one with an edit, the other as written
    waiting = pipeline.review.queue()
    assert len(waiting) == 2
    first, second = waiting
    edited = first.message.generated_body.replace(
        "Would one of the next two weeks", "Could one of the next two weeks"
    )
    pipeline.review.approve(first.message.id, edited_body=edited)
    pipeline.review.approve(second.message.id)

    # 4. delivery
    pipeline.runner.run_pipeline()
    assert statuses(factory, ws) == {"acme.co.uk": C.IN_SEQUENCE, "beta.com": C.IN_SEQUENCE}
    assert world.mailbox.appends == 2
    drafts = sorted(d.body for d in world.mailbox.drafts.values())
    assert edited in drafts

    # 5. the rerun gate: the same targets file again makes no paid call and no new draft
    paid_before, appends_before = paid_calls(factory, ws), world.mailbox.appends
    again = pipeline.intake.run(ROWS)
    assert [r.status for r in again.rows] == [ImportRowStatus.MERGED] * 2
    pipeline.runner.run_pipeline()
    assert paid_calls(factory, ws) == paid_before
    assert world.mailbox.appends == appends_before

    # 6. the operator sends one of them; the Sent sync notices
    sent_message = pipeline.review.show(first.message.id).item.message
    world.mailbox.sent.append(
        SentMessage(
            rfc_message_id="<sent-1@quantra.example>",
            to_address=first.address.email or "",
            subject=sent_message.subject,
            sent_at=datetime.now(UTC) + timedelta(minutes=10),
            body=edited,
        )
    )
    tick = pipeline.tick.run()
    assert tick.jobs["sent_sync"]["matched"] == 1
    with factory(ws) as uow:
        states = {m.state for m in uow.messages.in_state(MessageState.SENT)}
    assert states == {MessageState.SENT}

    quality = ReportService(factory, ws).quality()
    assert (quality.written, quality.sent, quality.unedited) == (2, 1, 0)
    assert quality.unedited_share == 0.0


def test_the_ledger_records_every_vendor_call_with_its_attribution(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    pipeline, _ = build(engine, factory, ws, world)
    pipeline.intake.run(ROWS[:1])
    run = pipeline.runner.run_pipeline()
    with factory(ws) as uow:
        calls = list(uow.session.scalars(select(ProviderCallRow)))
    providers = {c.provider for c in calls}
    assert {"fake-search", "fake-llm", "finder", "verifier"} <= providers
    assert {c.run_id for c in calls} == {run.run_id}
    assert all(c.company_id for c in calls)


def test_a_uk_sole_trader_is_held_and_nothing_further_is_spent_on_it(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()

    class Bare(SiteSearch):
        def extract(self, urls: list[str]) -> list[PageText]:
            domain = urls[0].split("//")[1]
            return [PageText(url=f"https://{domain}", text="Bob fixes boilers in Leeds. LS1 4AP.")]

    world.search = Bare()
    pipeline, _ = build(engine, factory, ws, world)
    pipeline.intake.run([{"Website": "bobs-boilers.co.uk"}])
    pipeline.runner.run_pipeline()
    with factory(ws) as uow:
        company = uow.companies.by_domain("bobs-boilers.co.uk")
        assert company is not None
        assert (company.status, company.hold_reason) == (C.HELD, HoldReason.ENTITY_UNKNOWN)
    assert world.finder.calls == 0 and world.verifier.calls == 0
    assert world.mailbox.appends == 0


def test_a_german_target_is_disqualified_before_any_email_is_paid_for(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    pipeline, _ = build(engine, factory, ws, world)
    pipeline.intake.run([{"Website": "acme.de", "Country": "DE"}])
    pipeline.runner.run_pipeline()
    assert statuses(factory, ws) == {"acme.de": C.DISQUALIFIED}
    assert world.finder.calls == 0


def test_the_pipeline_stops_cleanly_at_approved_when_no_mailbox_is_configured(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    providers = world.providers()
    no_mailbox = Providers(
        providers.search,
        providers.llm,
        providers.finders,
        providers.verifier,
        registry=providers.registry,
    )
    with factory(ws) as uow:
        row = uow.session.get(WorkspaceRow, ws)
        assert row is not None
        row.sender_profile = PROFILE
        uow.campaigns.create("default", ["CTO"], icp_description="Utilities")
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        uow.commit()
    pipeline = assemble(Container(Settings(_env_file=None), engine, factory), ws, no_mailbox)
    assert pipeline.has_mailbox is False and "deliver" not in pipeline.stage_names
    pipeline.intake.run(ROWS[:1])
    pipeline.runner.run_pipeline()
    pipeline.review.approve(pipeline.review.queue()[0].message.id)
    pipeline.runner.run_pipeline()
    assert statuses(factory, ws) == {"acme.co.uk": C.APPROVED}


def test_the_email_is_written_by_the_writer_model_when_one_is_set(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    """Research stays on LLM_MODEL; only the copy step uses LLM_COPY_MODEL."""
    world = World()
    writer = FakeLlm()
    writer.model = "strong/writer-model"
    pipeline, _ = build(
        engine, factory, ws, world, providers=replace(world.providers(), copy_llm=writer)
    )
    pipeline.intake.run(ROWS)
    pipeline.runner.run_pipeline()
    assert "site" in world.llm.calls and "actor" not in world.llm.calls
    assert "actor" in writer.calls and "site" not in writer.calls


def test_a_run_lists_every_lead_it_moved_held_or_failed_with_each_step(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    pipeline, _ = build(engine, factory, ws, world)
    pipeline.intake.run(ROWS)
    run = pipeline.runner.run_pipeline()
    leads = RunService(factory, ws).leads(run.run_id)
    assert sorted(lead.domain for lead in leads) == ["acme.co.uk", "beta.com"]
    first = next(lead for lead in leads if lead.domain == "beta.com")
    assert [(s.from_status, s.to_status) for s in first.steps] == [
        ("new", "researched"),
        ("researched", "qualified"),
        ("qualified", "contacts_found"),
        ("contacts_found", "email_ready"),
        ("email_ready", "copy_ready"),
    ]
    assert (first.status, first.outcome) == ("copy_ready", "moved")
    # A second run that has nothing to do lists nothing: only what a run itself did is its own.
    again = pipeline.runner.run_pipeline()
    assert RunService(factory, ws).leads(again.run_id) == []


def test_a_lead_the_run_failed_is_listed_with_the_error(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    world.llm.replies["site"] = "not json at all"
    pipeline, _ = build(engine, factory, ws, world)
    pipeline.intake.run(ROWS[:1])
    run = pipeline.runner.run_pipeline()
    [lead] = RunService(factory, ws).leads(run.run_id)
    assert lead.outcome == "failed"
    assert lead.steps[-1].to_status == "failed" and "JSON" in (lead.steps[-1].detail or "")
