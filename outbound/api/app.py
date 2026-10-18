"""The FastAPI application: thin routers over the services, one local login, one process.

The API never runs the pipeline inside a request. Runs are queued and the ``outbound worker``
process executes them, so the app stays responsive and a long run survives a page refresh.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from outbound.api import errors
from outbound.api.auth import LoginThrottle, Sessions, require_csrf_header, require_operator
from outbound.api.deps import Services
from outbound.api.errors import ApiError
from outbound.api.request_log import log_requests
from outbound.api.routers import auth, leads, privacy, review, runs, settings, targets, webhook
from outbound.bootstrap import Container
from outbound.domain.errors import ConfigurationError

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


SECURITY_HEADERS = {
    # Everything the page loads comes from this server; nothing may frame it (an invisible
    # frame over the Approve button would be click-jacking); nothing is guessed from content.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def create_app(services: Services, *, web_dist: Path | None = WEB_DIST) -> FastAPI:
    config = services.container.settings
    # The built-in docs page loads scripts from a CDN, which the content policy forbids, and
    # the API document is served below behind the login instead.
    app = FastAPI(
        title="Outbound", version="0.3.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.services = services
    app.state.password_hash = config.operator_password_hash
    app.state.sessions = Sessions(config.session_secret.get_secret_value(), config.session_hours)
    app.state.throttle = LoginThrottle()
    app.state.cookie_secure = config.cookie_secure
    app.state.webhook_secret = config.intake_webhook_secret.get_secret_value()
    errors.install(app)

    @app.middleware("http")
    async def secure_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # Added last, so it is outermost: the request id exists before anything else runs.
    app.middleware("http")(log_requests)

    guarded = [Depends(require_operator), Depends(require_csrf_header)]
    app.include_router(auth.router, dependencies=[Depends(require_csrf_header)])
    app.include_router(webhook.router)  # signed, so no login
    for router in (targets, review, leads, runs, settings, privacy):
        app.include_router(router.router, dependencies=guarded)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/openapi.json", include_in_schema=False, dependencies=[Depends(require_operator)])
    def api_document() -> dict[str, Any]:
        return app.openapi()

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def no_such_endpoint(path: str) -> None:
        # Last in line, so only paths no router claimed get here. The usual cause is a page newer
        # than the running server (the app was updated but the server was not restarted); without
        # this, a POST would fall through to the page route and answer "Method Not Allowed".
        raise ApiError(
            404,
            "no_such_endpoint",
            "The server has no such endpoint. If the app was just updated, restart it: stop "
            "`uv run outbound serve` and `uv run outbound worker` and start them again.",
        )

    if web_dist is not None and (web_dist / "index.html").exists():
        root = web_dist.resolve()
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise ApiError(404, "not_found", "No such endpoint.")
            return FileResponse(_file_inside(root, path) or root / "index.html")

    return app


def _file_inside(root: Path, requested: str) -> Path | None:
    """The file at ``requested`` under ``root``, or None.

    The path comes from the URL and may contain ``..`` or encoded separators, so it is resolved
    and must still be inside ``root``. Hidden files (``.env`` and the like) are never served.
    """
    try:
        candidate = (root / requested).resolve()
        relative = candidate.relative_to(root)
    except (ValueError, OSError):  # outside the root, or an invalid name such as a NUL byte
        return None
    if any(part.startswith(".") for part in relative.parts) or not candidate.is_file():
        return None
    return candidate


def create_app_from_container(container: Container) -> FastAPI:
    """Build the app for a real run: one workspace, search only if a Tavily key is set."""
    from outbound.api.deps import build_services
    from outbound.pipeline import metered_search_or_none
    from outbound.providers.registry import build_mailbox_if_configured

    config = container.settings
    if not config.operator_password_hash or not config.session_secret.get_secret_value():
        raise ConfigurationError(
            "The web app needs a login. Add two lines to .env:\n"
            "  OPERATOR_PASSWORD_HASH=<output of: uv run outbound auth hash-password>\n"
            "  SESSION_SECRET=<any random string of 32+ characters, for example the output of\n"
            '    python3 -c "import secrets; print(secrets.token_urlsafe(32))">'
        )
    workspace_id = container.workspace_id(config.workspace_name)
    return create_app(
        build_services(
            container,
            workspace_id,
            search=metered_search_or_none(container, workspace_id),
            mailbox=build_mailbox_if_configured(config),
        )
    )
