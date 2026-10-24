"""Each request gets services for its own workspace (Phase 6a): shared vendor clients, but
that workspace's meter and ledger."""

from __future__ import annotations

from sqlalchemy import Engine, text

from outbound.api.app import create_app
from outbound.api.deps import ServicesFactory
from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
from outbound.providers.adapters.transactional_email import LogEmail
from tests.api.conftest import ADMIN, add_user, sign_in
from tests.stages.fakes import FakeSearch


def ledger_rows(factory: UnitOfWorkFactory, workspace: str) -> int:
    with factory(workspace) as uow:
        count = uow.session.execute(
            text("SELECT count(*) FROM provider_calls WHERE workspace_id = :ws"),
            {"ws": workspace},
        ).scalar_one()
    return int(count)


def test_two_workspaces_get_their_own_meters_over_one_shared_client(
    engine: Engine, factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    search = FakeSearch()
    services = ServicesFactory(container_for(Settings(_env_file=None), engine), search=search)
    mine, theirs = services.for_tenant(ws), services.for_tenant(other_ws)
    assert (mine.workspace_id, theirs.workspace_id) == (ws, other_ws)

    mine.intake.run([{"Company": "Acme Energy"}])  # a name with no domain: one search

    assert (ledger_rows(factory, ws), ledger_rows(factory, other_ws)) == (1, 0)
    assert len(search.searches) == 1  # one shared client, called once


def test_what_a_person_does_is_recorded_as_them_not_as_the_operator(
    engine: Engine, platform_engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    container = container_for(Settings(_env_file=None), engine, platform_engine)
    app = create_app(ServicesFactory(container), web_dist=None, email=LogEmail())
    user_id = add_user(app, ADMIN, ws)
    sign_in(app, ADMIN).post("/api/targets", json={"website": "acme.com", "country": "UK"})
    with factory(ws) as uow:
        actors = set(
            uow.session.execute(
                text("SELECT DISTINCT actor FROM events WHERE workspace_id = :ws"), {"ws": ws}
            ).scalars()
        )
    assert f"user:{user_id}" in actors and "operator" not in actors
