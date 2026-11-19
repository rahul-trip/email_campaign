"""A stage's leads can be worked on side by side, with the same results as one at a time."""

from __future__ import annotations

import threading
import time

from sqlalchemy import select

from outbound.db.models import EventRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanyStatus, EntityType, RunStatus
from outbound.metering.budget import BudgetPolicy
from outbound.metering.metered import current_scope
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner
from outbound.stages.base import StageContext, StageResult
from tests.db.test_runner import FakeStage, add_company, company

C = CompanyStatus


class Probe:
    """A stage action that takes a moment, and notes how many leads were inside at once."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.inside = 0
        self.most = 0
        self.wrong_scope: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, ctx: StageContext) -> StageResult | None:
        with self._lock:
            self.inside += 1
            self.most = max(self.most, self.inside)
        if current_scope().company_id != ctx.company.id:
            self.wrong_scope.append(ctx.company.domain)
        time.sleep(self.delay)
        with self._lock:
            self.inside -= 1
        return None


def runner(factory: UnitOfWorkFactory, ws: str, stage: FakeStage, concurrency: int) -> Runner:
    return Runner(factory, ws, [stage], Guards(BudgetPolicy()), lead_concurrency=concurrency)


def leads(factory: UnitOfWorkFactory, ws: str, n: int) -> list[str]:
    return [add_company(factory, ws, f"lead{i}.com") for i in range(n)]


def test_leads_run_side_by_side_up_to_the_limit_with_the_same_results(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    ids = leads(factory, ws, 8)
    probe = Probe()
    report = runner(
        factory, ws, FakeStage("research", C.NEW, C.RESEARCHED, action=probe), 4
    ).run_pipeline()
    assert 2 <= probe.most <= 4
    assert report.counts["research"]["advanced"] == 8
    assert all(company(factory, ws, i).status is C.RESEARCHED for i in ids)


def test_one_at_a_time_is_still_the_default(factory: UnitOfWorkFactory, ws: str) -> None:
    leads(factory, ws, 5)
    probe = Probe(0.01)
    report = runner(
        factory, ws, FakeStage("research", C.NEW, C.RESEARCHED, action=probe), 1
    ).run_pipeline()
    assert probe.most == 1 and report.counts["research"]["advanced"] == 5


def test_each_lead_keeps_its_own_call_scope_and_run_id(factory: UnitOfWorkFactory, ws: str) -> None:
    ids = leads(factory, ws, 8)
    probe = Probe()
    report = runner(
        factory, ws, FakeStage("research", C.NEW, C.RESEARCHED, action=probe), 4
    ).run_pipeline()
    assert probe.wrong_scope == []  # every metered call would be booked to the right lead
    with factory(ws) as uow:
        changes = list(
            uow.session.scalars(
                select(EventRow).where(
                    EventRow.entity_type == EntityType.COMPANY,
                    EventRow.type == "status_changed",
                    EventRow.entity_id.in_(ids),
                )
            )
        )
    assert [e.data.get("run_id") for e in changes] == [report.run_id] * 8


def test_a_stage_that_shares_a_connection_stays_one_at_a_time(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    leads(factory, ws, 6)
    probe = Probe(0.01)
    stage = FakeStage("research", C.NEW, C.RESEARCHED, action=probe)
    stage.parallel = False  # type: ignore[attr-defined]
    runner(factory, ws, stage, 4).run_pipeline()
    assert probe.most == 1


def test_a_cancelled_run_stops_starting_leads(factory: UnitOfWorkFactory, ws: str) -> None:
    leads(factory, ws, 20)
    seen = 0
    lock = threading.Lock()

    def cancel_after_the_first(ctx: StageContext) -> StageResult | None:
        nonlocal seen
        with lock:
            seen += 1
            first = seen == 1
        if first:
            run = ctx.read(lambda uow: uow.runs.recent(1)[0])
            with factory(ws) as uow:
                uow.runs.cancel(run.id)
                uow.commit()
        time.sleep(0.05)
        return None

    stage = FakeStage("research", C.NEW, C.RESEARCHED, action=cancel_after_the_first)
    report = runner(factory, ws, stage, 4).run_pipeline()
    assert report.status is RunStatus.CANCELLED
    assert seen <= 8  # the leads already under way finish; no new ones start
