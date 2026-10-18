"""The FastAPI application: thin routers over the services, one local login, one process.

The API never runs the pipeline inside a request. Runs are queued and the ``outbound worker``
process executes them, so the app stays responsive and a long run survives a page refresh.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from outbound.api import errors
from outbound.api.auth import LoginThrottle, Sessions, require_csrf_header, require_operator
from outbound.api.deps import Services
from outbound.api.routers import auth, leads, review, runs, settings, targets, webhook
from outbound.bootstrap import Container

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def create_app(services: Services, *, web_dist: Path | None = WEB_DIST) -> FastAPI:
    config = services.container.settings
    app = FastAPI(
        title="Outbound", version="0.3.0", docs_url="/api/docs", openapi_url="/openapi.json"
    )
    app.state.services = services
    app.state.password_hash = config.operator_password_hash
    app.state.sessions = Sessions(config.session_secret.get_secret_value(), config.session_hours)
    app.state.throttle = LoginThrottle()
    app.state.cookie_secure = config.cookie_secure
    errors.install(app)

    guarded = [Depends(require_operator), Depends(require_csrf_header)]
    app.include_router(auth.router, dependencies=[Depends(require_csrf_header)])
    app.include_router(webhook.router)  # signed, so no login
    for router in (targets, review, leads, runs, settings):
        app.include_router(router.router, dependencies=guarded)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if web_dist is not None and (web_dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = web_dist / path
            return FileResponse(candidate if candidate.is_file() else web_dist / "index.html")

    return app


def create_app_from_container(container: Container) -> FastAPI:
    """Build the app for a real run: one workspace, search only if a Tavily key is set."""
    from outbound.api.deps import build_services
    from outbound.pipeline import metered_search_or_none

    config = container.settings
    if not config.operator_password_hash or not config.session_secret.get_secret_value():
        raise RuntimeError(
            "The web app needs a login. Add two lines to .env:\n"
            "  OPERATOR_PASSWORD_HASH=<output of: uv run outbound auth hash-password>\n"
            "  SESSION_SECRET=<any random string of 32+ characters, for example the output of\n"
            '    python3 -c "import secrets; print(secrets.token_urlsafe(32))">'
        )
    with container.uow.admin() as admin:
        workspace = admin.workspaces.by_name(config.workspace_name)
    if workspace is None:
        raise RuntimeError(f"no workspace named {config.workspace_name!r}: run `outbound seed`")
    return create_app(
        build_services(
            container, workspace.id, search=metered_search_or_none(container, workspace.id)
        )
    )
