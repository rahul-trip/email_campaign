from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Request

from outbound.api.deps import services
from outbound.api.errors import ApiError
from outbound.services.webhook import WebhookError, verify

router = APIRouter(prefix="/api/intake", tags=["intake"])
DEFAULT_SECRET_REF = "INTAKE_WEBHOOK_SECRET"


@router.post("/webhook")
async def webhook(request: Request) -> dict[str, Any]:
    """Signed intake for other systems. Not behind the operator login: the signature is the key."""
    svc = services(request)
    body = await request.body()
    settings = svc.settings.workspace_settings()
    secret = os.environ.get(settings.get("intake_webhook_secret_ref") or DEFAULT_SECRET_REF, "")
    try:
        verify(
            secret,
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
        result = svc.webhook.receive(payload)
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
