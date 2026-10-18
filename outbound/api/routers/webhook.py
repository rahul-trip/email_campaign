from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from outbound.api.deps import services
from outbound.api.errors import ApiError
from outbound.services.webhook import WebhookError, verify

router = APIRouter(prefix="/api/intake", tags=["intake"])
MAX_BODY_BYTES = 1_000_000


async def _read_body(request: Request) -> bytes:
    """The raw body, refusing anything over the cap before it is all in memory."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise ApiError(413, "body_too_large", "The request body is larger than 1 MB.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise ApiError(413, "body_too_large", "The request body is larger than 1 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/webhook")
async def webhook(request: Request) -> dict[str, Any]:
    """Signed intake for other systems. Not behind the operator login: the signature is the key."""
    body = await _read_body(request)
    try:
        verify(
            request.app.state.webhook_secret,
            body,
            request.headers.get("x-signature"),
            request.headers.get("x-timestamp"),
        )
        try:
            payload = json.loads(body)
        except ValueError:
            raise WebhookError(422, "bad_json", "The body is not valid JSON.") from None
        if not isinstance(payload, dict):
            raise WebhookError(422, "bad_json", "The body must be a JSON object.")
        # Intake searches and writes, so it must not run on the event loop.
        result = await run_in_threadpool(services(request).webhook.receive, payload)
    except WebhookError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    if result.duplicate or result.report is None:
        return {"duplicate": True}
    return {
        "duplicate": False,
        "batch_id": result.report.batch_id,
        "rows": [
            {"status": r.status.value, "domain": r.domain, "reason": r.reason}
            for r in result.report.rows
        ],
    }
