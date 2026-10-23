"""The multi-tenant worker (Phase 6a): every workspace's queued runs and ticks, fairly, each in
its own workspace, with stale runs recovered."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Engine, text

from outbound.bootstrap import Container, container_for
from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import RunKind, RunStatus, WorkspaceStatus
from outbound.pipeline import Pipeline
from outbound.services.runs import RunRequest, RunService
from outbound.worker import Job, Task, Worker
from tests.db.test_pipeline_e2e import ROWS, build
from tests.stages.world import World


@pytest.fixture
def worker_container(engine: Engine, platform_engine: Engine) -> Container:
    """As in production: tenant work as outbound_app, cross-workspace reads as the platform."""
    return container_for(Settings(_env_file=None), engine, platform_engine)


def no_pipeline(workspace_id: str) -> Pipeline:
    raise AssertionError(f"no pipeline should be needed for {workspace_id}")


class Clock:
    def __init__(self) -> None:
        self.at = utcnow()

    def __call__(self) -> datetime:
        return self.at


def queue(factory: UnitOfWorkFactory, ws: str) -> str:
    return RunService(factory, ws).queue(RunRequest()).id


def run_status(factory: UnitOfWorkFactory, ws: str, run_id: str) -> RunStatus:
    with factory(ws) as uow:
        return uow.runs.get(run_id).status


def test_queued_runs_in_two_workspaces_each_run_in_their_own_workspace(
    worker_container: Container, engine: Engine, factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    pipelines: dict[str, Pipeline] = {}
    for workspace in (ws, other_ws):
        pipeline, _ = build(engine, factory, workspace, World())
        pipeline.intake.run(ROWS)
        pipelines[workspace] = pipeline
    assembled: list[str] = []

    def assemble(workspace_id: str) -> Pipeline:
        assembled.append(workspace_id)
        return pipelines[workspace_id]

    worker = Worker(worker_container, assemble, tick_every=None)
    runs = {workspace: queue(factory, workspace) for workspace in (ws, other_ws)}

    assert worker.run_once() is True
    assert sorted(assembled) == sorted([ws, other_ws])  # a pipeline per run, per workspace
    for workspace, run_id in runs.items():
        assert run_status(factory, workspace, run_id) is RunStatus.SUCCEEDED
        with factory(workspace) as uow:  # every ledger row belongs to a lead of its workspace
            foreign = uow.session.execute(
                text(
                    "SELECT count(*) FROM provider_calls p WHERE p.workspace_id = :ws AND "
                    "p.company_id IS NOT NULL AND p.company_id NOT IN "
                    "(SELECT id FROM companies WHERE workspace_id = :ws)"
                ),
                {"ws": workspace},
            ).scalar_one()
            calls = uow.session.execute(
                text("SELECT count(*) FROM provider_calls WHERE workspace_id = :ws"),
                {"ws": workspace},
            ).scalar_one()
        assert foreign == 0 and calls > 0
    assert worker.run_once() is False  # nothing else is waiting


def test_a_queued_pipeline_waits_while_its_workspace_has_one_running(
    worker_container: Container, engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        uow.runs.start(RunKind.PIPELINE, {})
        uow.commit()
    waiting = queue(factory, ws)
    worker = Worker(
        worker_container,
        no_pipeline,
        tick_every=None,
    )
    assert worker.execute(Job(ws, Task.RUN)) is False
    assert run_status(factory, ws, waiting) is RunStatus.QUEUED


def test_a_paused_workspace_gets_no_work(
    worker_container: Container,
    engine: Engine,
    platform: PlatformUnitOfWorkFactory,
    factory: UnitOfWorkFactory,
    ws: str,
) -> None:
    queue(factory, ws)
    with platform() as directory:
        directory.workspaces.set_status(ws, WorkspaceStatus.PAUSED)
        directory.commit()
    worker = Worker(worker_container, no_pipeline)
    assert worker.plan() == []


def test_planning_skips_busy_workspaces_and_serves_the_least_recent_first(
    worker_container: Container, engine: Engine, factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    queue(factory, ws)
    queue(factory, other_ws)
    clock = Clock()
    worker = Worker(
        worker_container,
        no_pipeline,
        tick_every=None,
        now=clock,
    )
    worker._last_served = {ws: clock.at, other_ws: clock.at - timedelta(hours=1)}
    assert [job.workspace_id for job in worker.plan()] == [other_ws, ws]
    worker._busy = {other_ws}
    assert [job.workspace_id for job in worker.plan()] == [ws]


def test_each_active_workspace_gets_a_tick_on_its_timer(
    worker_container: Container, engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    clock = Clock()
    ticks: list[str] = []

    class Ticking:
        def run(self, *, limit: int, skip_idle: bool) -> None:
            assert skip_idle
            ticks.append("tick")

    class Assembled:
        tick = Ticking()

    worker = Worker(
        worker_container,
        lambda _ws: cast(Pipeline, Assembled()),
        tick_every=timedelta(minutes=15),
        now=clock,
    )
    assert worker.plan() == [Job(ws, Task.TICK)]
    worker.run_once()
    assert ticks == ["tick"]
    assert worker.plan() == []  # not again until the timer comes round
    clock.at += timedelta(minutes=15)
    assert worker.plan() == [Job(ws, Task.TICK)]


def test_a_run_whose_worker_died_is_failed_in_whichever_workspace(
    worker_container: Container, engine: Engine, factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(other_ws) as uow:
        stale = uow.runs.start(RunKind.PIPELINE, {})
        uow.commit()
    clock = Clock()
    clock.at += timedelta(hours=1)
    worker = Worker(
        worker_container,
        no_pipeline,
        tick_every=None,
        now=clock,
    )
    assert worker.recover_stale() == [stale]
    assert run_status(factory, other_ws, stale) is RunStatus.FAILED
