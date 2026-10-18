"""Problem-details errors (RFC 9457) with stable codes the web app can switch on."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.domain.errors import InvalidInput
from outbound.domain.state_machines import IllegalTransition
from outbound.logging import get_logger
from outbound.services.leads import LeadError
from outbound.services.review import ReviewError
from outbound.services.settings import SettingsError

PROBLEM = "application/problem+json"
log = get_logger(__name__)


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, detail: str, extra: dict[str, Any] | None = None
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra or {}


def problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    body = {"type": f"urn:outbound:{code}", "title": code, "status": status, "detail": detail}
    return JSONResponse({**body, "code": code, **extra}, status_code=status, media_type=PROBLEM)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, error: ApiError) -> JSONResponse:
        return problem(error.status, error.code, error.detail, **error.extra)

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, error: NotFound) -> JSONResponse:
        return problem(404, "not_found", "That does not exist in this workspace.")

    @app.exception_handler(ConcurrencyConflict)
    async def _conflict(request: Request, error: ConcurrencyConflict) -> JSONResponse:
        return problem(
            409, "version_conflict", "It changed since you loaded it. Reload and try again."
        )

    @app.exception_handler(LeadError)
    @app.exception_handler(ReviewError)
    @app.exception_handler(IllegalTransition)
    async def _state(request: Request, error: Exception) -> JSONResponse:
        return problem(409, "action_not_allowed", str(error))

    @app.exception_handler(SettingsError)
    @app.exception_handler(InvalidInput)
    async def _invalid(request: Request, error: Exception) -> JSONResponse:
        return problem(422, "invalid_request", str(error))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, error: Exception) -> JSONResponse:
        # A bug: say nothing about it to the client, and keep the details in the log.
        log.exception("unhandled_error", path=request.url.path)
        return problem(500, "internal_error", "Something went wrong. It has been logged.")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, error: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
            for e in error.errors()
        ]
        return problem(422, "validation_failed", "Some fields are not valid.", errors=fields)
