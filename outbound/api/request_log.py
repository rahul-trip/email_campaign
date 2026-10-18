"""One log line per request, and a request id that ties every line of that request together."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from outbound.logging import bind, clear, get_logger

log = get_logger("outbound.http")

HEADER = "X-Request-ID"
_ACCEPTABLE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Polled by the page every few seconds, or static files: DEBUG, not a line each time.
_QUIET_PREFIXES = ("/api/health", "/api/status", "/assets/")


def request_id_for(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or "unknown"


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    # A caller's id is kept so a request can be followed across systems, but only if it is
    # well formed: it ends up in logs and a response header.
    supplied = request.headers.get(HEADER, "")
    request_id = supplied if _ACCEPTABLE.match(supplied) else uuid.uuid4().hex
    request.state.request_id = request_id
    client_ip = request.client.host if request.client else "unknown"
    clear()
    bind(request_id=request_id, client_ip=client_ip)
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        # The error handler logs the traceback; this line records that the request ended in 500.
        _log(request, 500, started)
        raise
    response.headers[HEADER] = request_id
    _log(request, response.status_code, started)
    return response


def _log(request: Request, status: int, started: float) -> None:
    route = request.scope.get("route")
    # The route template (/api/companies/{company_id}) groups requests; the query string is
    # never logged because it can carry anything.
    path = getattr(route, "path", None) or request.url.path[:200]
    fields = {
        "method": request.method,
        "path": path,
        "status": status,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    if request.url.path.startswith(_QUIET_PREFIXES) and status < 400:
        log.debug("http_request", **fields)
    elif status >= 500:
        log.error("http_request", **fields)
    elif status >= 400:
        log.warning("http_request", **fields)
    else:
        log.info("http_request", **fields)
