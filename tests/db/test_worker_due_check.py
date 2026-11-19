"""Work that appears between ticks starts within minutes, and a pass that moved leads is followed
at once by another look; a pass that moved nothing is not retried in a loop."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine, func, select

from outbound.bootstrap import Container, container_for
from outbound.config import Settings
from outbound.db.models import RunRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.worker import Job, Task, Worker
from tests.db.test_pipeline_e2e import ROWS, build
from tests.db.test_scheduler import Clock, no_pipeline
from tests.stages.world import World


@pytest.fixture
def worker_container(engine: Engine, platform_engine: Engine) -> Container:
    return container_for(Settings(_env_file=None), engine, platform_engine)


EVERY_TICK = timedelta(minutes=15)
EVERY_CHECK = timedelta(minutes=2)


def runs(factory: UnitOfWorkFactory, ws: str) -> int:
    with factory(ws) as uow:
        return int(uow.session.scalar(select(func.count()).select_from(RunRow)) or 0)


def timed(container: Container, assemble, clock: Clock) -> Worker:  # type: ignore[no-untyped-def]
    return Worker(
        container, assemble, tick_every=EVERY_TICK, due_check_every=EVERY_CHECK, now=clock
    )


def test_an_idle_workspace_costs_one_query_and_no_run(
    worker_container: Container,
    factory: UnitOfWorkFactory,
    ws: str,
) -> None:
    clock = Clock()
    worker = timed(worker_container, no_pipeline, clock)  # assembling a pipeline would fail
    assert worker.execute(Job(ws, Task.PIPELINE)) is False
    assert runs(factory, ws) == 0


def test_a_due_lead_is_picked_up_by_the_light_check_not_the_tick(
    worker_container: Container,
    engine: Engine,
    factory: UnitOfWorkFactory,
    ws: str,
) -> None:
    pipeline, _ = build(engine, factory, ws, World())
    pipeline.intake.run(ROWS)
    clock = Clock()
    worker = timed(worker_container, lambda _ws: pipeline, clock)
    assert worker.execute(Job(ws, Task.PIPELINE)) is True
    assert runs(factory, ws) == 1
    with factory(ws) as uow:  # the leads were worked on
        assert all(c.status.value != "new" for c in uow.companies.search(limit=50)[0])


def test_after_a_pass_that_moved_leads_the_next_look_is_at_once_and_otherwise_on_the_interval(
    worker_container: Container,
    engine: Engine,
    factory: UnitOfWorkFactory,
    ws: str,
) -> None:
    pipeline, _ = build(engine, factory, ws, World())
    pipeline.intake.run(ROWS)
    clock = Clock()
    worker = timed(worker_container, lambda _ws: pipeline, clock)
    worker._last_tick[ws] = clock.at  # ticked just now, so only the light check is in question
    assert worker.execute(Job(ws, Task.PIPELINE)) is True  # the leads move
    assert worker.plan() == [Job(ws, Task.PIPELINE)]  # leads moved: look again now
    assert worker.execute(Job(ws, Task.PIPELINE)) is False  # nothing is due any more
    assert worker.plan() == []  # and a pass that moved nothing waits for the interval
    clock.at += timedelta(minutes=1)
    assert worker.plan() == []
    clock.at += timedelta(minutes=1)
    assert worker.plan() == [Job(ws, Task.PIPELINE)]


def test_the_tick_keeps_its_own_timer(
    worker_container: Container,
    factory: UnitOfWorkFactory,
    ws: str,
) -> None:
    clock = Clock()
    worker = timed(worker_container, no_pipeline, clock)
    assert worker.plan() == [Job(ws, Task.TICK)]  # never ticked: the tick, not a light check
    worker._last_tick[ws] = clock.at
    worker._last_due_check[ws] = clock.at
    assert worker.plan() == []
    clock.at += EVERY_CHECK
    assert worker.plan() == [Job(ws, Task.PIPELINE)]  # a light check between ticks
    clock.at += EVERY_TICK
    assert worker.plan() == [Job(ws, Task.TICK)]


def test_without_a_due_check_interval_only_the_tick_starts_work(
    worker_container: Container,
    factory: UnitOfWorkFactory,
    ws: str,
) -> None:
    clock = Clock()
    worker = Worker(worker_container, no_pipeline, tick_every=EVERY_TICK, now=clock)
    worker._last_tick[ws] = clock.at
    clock.at += timedelta(minutes=10)
    assert worker.plan() == []
