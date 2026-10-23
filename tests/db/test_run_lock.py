"""One running pipeline per workspace, the run heartbeat, stale-run recovery and the live budget
(Phase 3b items B2, B3 and B4, prerequisites of Phase 6a)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from outbound.db.errors import RunInProgress
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import RunKind, RunStatus
from outbound.metering.budget import BudgetPolicy


def test_a_second_pipeline_run_in_the_same_workspace_is_refused(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        uow.runs.start(RunKind.PIPELINE, {})
        uow.commit()
    with factory(ws) as uow, pytest.raises(RunInProgress):
        uow.runs.start(RunKind.PIPELINE, {})


def test_another_workspace_may_run_at_the_same_time(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    for workspace in (ws, other_ws):
        with factory(workspace) as uow:
            uow.runs.start(RunKind.PIPELINE, {})
            uow.commit()


def test_a_sync_run_does_not_block_a_pipeline(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.runs.start(RunKind.SYNC, {})
        uow.runs.start(RunKind.PIPELINE, {})
        uow.commit()


def test_a_queued_pipeline_waits_while_another_is_running(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        running = uow.runs.start(RunKind.PIPELINE, {})
        queued = uow.runs.queue(RunKind.PIPELINE, {})
        uow.commit()
    with factory(ws) as uow:
        assert uow.runs.claim_next() is None
        uow.runs.finish(running, RunStatus.SUCCEEDED)
        uow.commit()
    with factory(ws) as uow:
        claimed = uow.runs.claim_next()
        uow.commit()
    assert claimed is not None and claimed.id == queued


def test_a_run_without_a_recent_heartbeat_is_failed(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        stale = uow.runs.start(RunKind.PIPELINE, {})
        uow.commit()
    with factory(ws) as uow:
        assert uow.runs.fail_stale(utcnow() - timedelta(minutes=30)) == []
        assert uow.runs.fail_stale(utcnow() + timedelta(seconds=1)) == [stale]
        uow.commit()
    with factory(ws) as uow:
        run = uow.runs.get(stale)
        assert run.status is RunStatus.FAILED
        assert run.counts == {"error": "worker stopped (no heartbeat)"}
        uow.runs.start(RunKind.PIPELINE, {})  # the queue is free again


def test_a_heartbeat_keeps_a_run_alive(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        run_id = uow.runs.start(RunKind.PIPELINE, {})
        uow.commit()
    cutoff = utcnow()
    with factory(ws) as uow:
        uow.runs.heartbeat(run_id)
        uow.commit()
    with factory(ws) as uow:
        assert uow.runs.fail_stale(cutoff) == []


def test_the_live_budget_follows_the_workspace_setting(factory: UnitOfWorkFactory, ws: str) -> None:
    policy = BudgetPolicy.live_from({})
    with factory(ws) as uow:
        assert policy.ceiling(uow) is None
    with factory.admin() as admin:
        admin.workspaces.set_settings(ws, {"budget_per_prospect_micro_usd": 250_000})
        admin.commit()
    with factory(ws) as uow:
        assert policy.ceiling(uow) == 250_000
