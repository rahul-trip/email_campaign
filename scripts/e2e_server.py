"""A self-contained server for the browser smoke test: real app, real worker, fake vendors.

    uv run python -m scripts.e2e_server

It starts on a throwaway database with a seeded workspace, serves ``web2/dist`` (or the folder
in ``E2E_WEB_DIST``, which the legacy ``web/`` tests set), and runs a
worker thread that executes queued runs against fake search, model, finder and mailbox
objects. No network and no keys are used. The password is printed in ``E2E_PASSWORD``.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from pydantic import SecretStr

from outbound.api.app import WEB_DIST, create_app
from outbound.api.auth import hash_password
from outbound.api.deps import build_services
from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.db import migrate
from outbound.db.session import make_engine, make_session_factory
from outbound.db.uow import UnitOfWorkFactory
from outbound.metering.metered import MeteredLlm
from outbound.pipeline import assemble, build_meter
from outbound.services.seed import seed_defaults
from outbound.worker import Worker
from tests.stages.world import PROFILE, World

E2E_PASSWORD = "e2e-password-123"
PORT = 8765


def build() -> tuple[FastAPI, Worker]:
    folder = Path(tempfile.mkdtemp(prefix="outbound-e2e-"))
    url = f"sqlite:///{folder / 'e2e.db'}"
    migrate.upgrade(url)
    engine = make_engine(url)
    factory = UnitOfWorkFactory(make_session_factory(engine))
    seed_defaults(factory, "default")
    with factory.admin() as admin:
        workspace = admin.workspaces.by_name("default")
        assert workspace is not None
        admin.workspaces.set_sender_profile(workspace.id, {**workspace.sender_profile, **PROFILE})
        admin.commit()
    settings = Settings(
        _env_file=None,
        database_url=url,
        operator_password_hash=hash_password(E2E_PASSWORD),
        session_secret=SecretStr("e2e-session-secret-0123456789"),
    )
    container = Container(settings, engine, factory)
    world = World()
    pipeline = assemble(container, workspace.id, world.providers())
    web_dist = Path(os.environ["E2E_WEB_DIST"]) if os.environ.get("E2E_WEB_DIST") else WEB_DIST
    # Revisions on Review use the fake world's model too, metered like the real one.
    writer = MeteredLlm(world.llm, build_meter(container, workspace.id))
    app = create_app(build_services(container, workspace.id, writer=writer), web_dist=web_dist)
    return app, Worker(container, workspace.id, pipeline)


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
