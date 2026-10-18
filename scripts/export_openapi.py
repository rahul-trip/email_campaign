"""Print the API's OpenAPI document, so the web client can be generated from it.

    uv run python -m scripts.export_openapi > web/openapi.json

It builds the app against a throwaway database; nothing is read from or written to yours.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from pydantic import SecretStr

from outbound.api.app import create_app
from outbound.api.deps import build_services
from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.db import migrate
from outbound.db.session import make_engine, make_session_factory
from outbound.db.uow import UnitOfWorkFactory


def build_document() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as folder:
        url = f"sqlite:///{Path(folder) / 'openapi.db'}"
        migrate.upgrade(url)
        engine = make_engine(url)
        factory = UnitOfWorkFactory(make_session_factory(engine))
        with factory.admin() as admin:
            workspace = admin.workspaces.create("docs", {}, {})
            admin.commit()
        settings = Settings(
            _env_file=None,
            database_url=url,
            operator_password_hash="x",
            session_secret=SecretStr("x" * 32),
        )
        app = create_app(
            build_services(Container(settings, engine, factory), workspace.id), web_dist=None
        )
        document = app.openapi()
        engine.dispose()
    return dict(document)


def main() -> int:
    json.dump(build_document(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
