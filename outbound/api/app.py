"""The FastAPI application: thin routers over the services, people signed in by email.

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
from outbound.api.auth import LoginThrottle, require_csrf_header
from outbound.api.deps import (
    FixedServices,
    Services,
    ServicesFactory,
    ServicesSource,
    current_user,
)
from outbound.api.errors import ApiError
from outbound.api.request_log import log_requests
from outbound.api.routers import (
    admin,
    auth,
    leads,
    mailboxes,
    privacy,
    review,
    runs,
    settings,
    targets,
    team,
    webhook,
)
from outbound.bootstrap import Container
from outbound.providers.ports import TransactionalEmail
from outbound.services.identity import IdentityService

# The built web app.
WEB_DIST = Path(__file__).resolve().parents[2] / "web2" / "dist"


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


def create_app(
    services: Services | ServicesFactory,
    *,
    workspace_id: str | None = None,
    web_dist: Path | None = WEB_DIST,
    email: TransactionalEmail | None = None,
) -> FastAPI:
    """The app over prebuilt services (tests, scripts) or a factory that builds them per
    request (a real run). ``workspace_id`` is the workspace the intake webhook feeds until
    Phase 6c gives each workspace its own; with prebuilt services it is theirs. ``email``
    sends invitations and resets (default: built from the settings)."""
    if isinstance(services, Services):
        source: ServicesSource = FixedServices(services)
        workspace_id = services.workspace_id
    else:
        if workspace_id is None:
            raise ValueError("a services factory needs the workspace it serves")
        source = services
    container = services.container
    config = container.settings
    if email is None:
        from outbound.providers.registry import build_transactional_email

        email = build_transactional_email(config)
    # The built-in docs page loads scripts from a CDN, which the content policy forbids, and
    # the API document is served below behind the login instead.
    app = FastAPI(
        title="Outbound", version="0.3.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.services_source = source
    app.state.workspace_id = workspace_id
    app.state.container = container
    app.state.identity = IdentityService(
        container.identity,
        container.platform,
        container.uow,
        email,
        base_url=config.app_base_url,
        terms_version=config.terms_version,
    )
    app.state.superadmin_enabled = config.superadmin_enabled
    app.state.superadmin_views = set()
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

    # Each route checks its own permission (``require`` in deps); this adds the write header.
    csrf = [Depends(require_csrf_header)]
    app.include_router(webhook.router)  # signed, so no sign-in
    for router in (auth, team, admin, mailboxes, targets, review, leads, runs, settings, privacy):
        app.include_router(router.router, dependencies=csrf)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/openapi.json", include_in_schema=False, dependencies=[Depends(current_user)])
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
    """Build the app for a real run: search only if a Tavily key is set."""
    from outbound.pipeline import search_or_none, writer_or_none

    config = container.settings
    workspace_id = container.workspace_id(config.workspace_name)
    factory = ServicesFactory(
        container,
        search=search_or_none(config),
        writer=writer_or_none(config),
    )
    return create_app(factory, workspace_id=workspace_id)
