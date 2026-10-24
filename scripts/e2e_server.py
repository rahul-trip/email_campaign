"""A self-contained server for the browser smoke test: real app, real worker, fake vendors.

    uv run python -m scripts.e2e_server

It starts on a throwaway database with a seeded workspace, serves ``web2/dist`` (or the folder
in ``E2E_WEB_DIST``), and runs a worker thread that executes queued runs against fake search,
model, finder and mailbox objects. No network and no keys are used.

Sign in as ``E2E_EMAIL`` with ``E2E_PASSWORD`` (a workspace admin), or as ``E2E_STAFF`` (a
superadmin with no workspace of their own). ``GET /e2e/outbox`` lists the emails the app would
have sent, so a test can follow an invitation or reset link.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from outbound.api.app import WEB_DIST, create_app
from outbound.api.deps import ServicesFactory
from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db import migrate
from outbound.db.crypto import new_key
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.session import make_engine, make_session_factory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import PlatformRole
from outbound.pipeline import assemble
from outbound.providers.adapters.transactional_email import LogEmail
from outbound.services.seed import seed_defaults
from outbound.worker import Worker
from tests.stages.world import PROFILE, World

E2E_EMAIL = "operator@e2e.example"
E2E_STAFF = "staff@e2e.example"
E2E_PASSWORD = "e2e-password-1234567"
PORT = 8765


def platform_default_id(platform: PlatformUnitOfWorkFactory) -> str:
    with platform() as directory:
        found = directory.workspaces.by_name("default")
    assert found is not None
    return found.id


def build() -> tuple[FastAPI, Worker]:
    folder = Path(tempfile.mkdtemp(prefix="outbound-e2e-"))
    url = f"sqlite:///{folder / 'e2e.db'}"
    migrate.upgrade(url)
    engine = make_engine(url)
    factory = UnitOfWorkFactory(make_session_factory(engine))
    platform = PlatformUnitOfWorkFactory(make_session_factory(engine))
    seed_defaults(factory, platform, "default")
    with factory(platform_default_id(platform)) as uow:  # a campaign the fake world can rank for
        [campaign] = uow.campaigns.all()
        uow.campaigns.update(
            campaign.id, {"target_titles": ["CTO"], "icp_description": "Utilities"}
        )
        uow.commit()
    with platform() as directory:
        workspace = directory.workspaces.by_name("default")
        assert workspace is not None
    with factory(workspace.id) as uow:
        uow.own_workspace.set_sender_profile({**workspace.sender_profile, **PROFILE})
        uow.commit()
    settings = Settings(
        _env_file=None,
        database_url=url,
        secrets_keys=SecretStr(json.dumps({"1": new_key()})),  # a throwaway key for this run
    )
    container = container_for(settings, engine)
    world = World()
    pipeline = assemble(container, workspace.id, world.providers())
    web_dist = Path(os.environ["E2E_WEB_DIST"]) if os.environ.get("E2E_WEB_DIST") else WEB_DIST
    outbox = LogEmail()
    # Like a real run: services are built per request for whichever workspace is asked for, so a
    # workspace made during a test works. Rewrites use the fake world's model, metered as usual.
    app = create_app(
        ServicesFactory(container, search=world.search, writer=world.llm),
        web_dist=web_dist,
        email=outbox,
    )
    _serve_outbox(app, outbox)
    with factory(workspace.id) as uow:  # a mailbox to look after in the browser (no real server)
        uow.mailboxes.create("sam@quantra-e2e.example", "quantra-e2e.example")
        uow.commit()
    app.state.identity.add_user(E2E_EMAIL, E2E_PASSWORD, name="Sam", workspace_id=workspace.id)
    app.state.identity.add_user(E2E_STAFF, E2E_PASSWORD, platform_role=PlatformRole.SUPERADMIN)
    return app, Worker(container, lambda _ws: pipeline, tick_every=None)


def _serve_outbox(app: FastAPI, outbox: LogEmail) -> None:
    """``GET /e2e/outbox``: every email the app would have sent, so a browser test can follow an
    invitation or reset link. Test server only; the real app has no such route."""

    @app.middleware("http")
    async def outbox_route(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path != "/e2e/outbox":
            return await call_next(request)
        return JSONResponse(
            [{"to": m.to, "subject": m.subject, "text": m.text} for m in outbox.sent]
        )


def main() -> None:
    app, worker = build()
    stop = threading.Event()
    threading.Thread(
        target=lambda: worker.run_forever(poll_seconds=0.2, stop=stop.is_set), daemon=True
    ).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
