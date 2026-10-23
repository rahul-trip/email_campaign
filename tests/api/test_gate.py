"""The Phase 3 gate: nothing reaches the mailbox without an approval made through the app.

The API queues work and the worker executes it, exactly as in production, with fake vendors.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from outbound.api.app import create_app
from outbound.api.auth import hash_password
from outbound.api.deps import build_services
from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.models import WorkspaceRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import RunStatus
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.pipeline import assemble
from outbound.worker import Worker
from tests.api.conftest import HEADERS, PASSWORD, Api
from tests.stages.world import PROFILE, World


def build(
    engine: Engine, platform_engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> tuple[Api, Worker, World]:
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        row = uow.session.get(WorkspaceRow, ws)
        assert row is not None
        row.sender_profile = PROFILE
        uow.campaigns.create("default", ["CTO"], icp_description="Utilities that need forecasts")
        uow.commit()
    settings = Settings(
        _env_file=None,
        operator_password_hash=hash_password(PASSWORD),
        session_secret=SecretStr("s" * 40),
    )
    container = container_for(settings, engine, platform_engine)
    world = World()
    pipeline = assemble(container, ws, world.providers())
    app: FastAPI = create_app(build_services(container, ws), web_dist=None)
    client = TestClient(app)
    client.post("/api/auth/login", json={"password": PASSWORD}, headers=HEADERS)
    return Api(client), Worker(container, lambda _ws: pipeline, tick_every=None), world


def test_the_whole_loop_in_the_browser_api_and_nothing_is_drafted_unapproved(
    engine: Engine, platform_engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    api, worker, world = build(engine, platform_engine, factory, ws)

    # add targets, as the Targets screen does
    for site in ("acme.co.uk", "beta.com"):
        added = api.post(
            "/api/targets", json={"website": site, "country": "UK" if "uk" in site else "US"}
        )
        assert added.json()["rows"][0]["status"] == "accepted"

    # start a run; the API only queues it
    run = api.post("/api/runs", json={}).json()
    assert run["status"] == "queued" and world.mailbox.appends == 0
    assert worker.run_once() is True
    assert api.get(f"/api/runs/{run['id']}").json()["status"] == RunStatus.SUCCEEDED.value
    assert worker.run_once() is False  # nothing else is waiting

    # both leads wait in the review queue; nothing has reached the mailbox
    queue = api.get("/api/review").json()
    assert len(queue) == 2
    assert world.mailbox.appends == 0

    # approve ONE of them through the app, then run again
    approved, ignored = queue
    assert api.post(f"/api/review/{approved['message']['id']}/approve", json={}).status_code == 200
    api.post("/api/runs", json={})
    worker.run_once()

    # only the approved lead was drafted; the other was never touched
    assert world.mailbox.appends == 1
    drafted_to = {d.to_address for d in world.mailbox.drafts.values()}
    assert drafted_to == {approved["contact"]["emails"][0]["email"]}
    ignored_company = api.get(f"/api/companies/{ignored['company']['id']}").json()["company"]
    assert ignored_company["status"] == "copy_ready"

    # and it stays that way however often the pipeline runs
    for _ in range(2):
        api.post("/api/runs", json={})
        worker.run_once()
    assert world.mailbox.appends == 1


def test_a_cancelled_queued_run_is_never_executed(
    engine: Engine, platform_engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    api, worker, _world = build(engine, platform_engine, factory, ws)
    api.post("/api/targets", json={"website": "acme.co.uk"})
    run = api.post("/api/runs", json={}).json()
    api.post(f"/api/runs/{run['id']}/cancel")
    assert worker.run_once() is False
    assert api.get("/api/review").json() == []


def test_a_failing_run_is_recorded_and_the_worker_carries_on(
    engine: Engine, platform_engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    api, worker, _world = build(engine, platform_engine, factory, ws)
    request = {"mode": "discovery", "campaign": "no-such-campaign"}
    bad = api.post("/api/runs", json=request).json()
    assert worker.run_once() is True
    failed = api.get(f"/api/runs/{bad['id']}").json()
    assert failed["status"] == "failed" and "no-such-campaign" in failed["counts"]["error"]
    api.post("/api/targets", json={"website": "acme.co.uk"})
    api.post("/api/runs", json={})
    assert worker.run_once() is True
    assert len(api.get("/api/review").json()) == 1
