"""Each request gets services for its own workspace (Phase 6a): shared vendor clients, but
that workspace's meter and ledger."""

from __future__ import annotations

from sqlalchemy import Engine, text

from outbound.api.deps import ServicesFactory
from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
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
