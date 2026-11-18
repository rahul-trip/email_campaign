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

    # A name with no domain: the name, then its homepage, when the first finds no site.
    mine.intake.run([{"Company": "Acme Energy"}])

    assert (ledger_rows(factory, ws), ledger_rows(factory, other_ws)) == (2, 0)
    assert len(search.searches) == 2  # one shared client, every call on my meter


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


def test_a_request_uses_the_live_vendors_and_their_change(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    """The web server uses the keys an admin manages (as the worker does), not only the ones it
    started with: a request built after a change gets the new client."""
    first, second = FakeSearch(), FakeSearch()
    live = {"search": first}
    services = ServicesFactory(
        container_for(Settings(_env_file=None), engine),
        search=FakeSearch(),  # what it started with: never used when ``live`` is given
        live=lambda: (live["search"], None),
    )
    services.for_tenant(ws).intake.run([{"Company": "Acme Energy"}])
    live["search"] = second
    services.for_tenant(ws).intake.run([{"Company": "Bolt Grid"}])
    assert first.searches and second.searches


def test_the_live_vendors_are_read_at_most_every_interval_and_survive_a_failure() -> None:
    from outbound.api.app import checked_every

    calls = {"n": 0}

    def get() -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("database away")
        return f"v{calls['n']}"

    every_time = checked_every(0, get, lambda: "env")
    assert every_time() == "v1"
    assert every_time() == "v1"  # the read failed: the last answer serves
    assert every_time() == "v3"
    failing = checked_every(0, lambda: (_ for _ in ()).throw(RuntimeError()), lambda: "env")
    assert failing() == "env"  # never read: the environment's
    cached = checked_every(3600, get, lambda: "env")
    assert cached() == cached()  # within the interval it is not asked again
