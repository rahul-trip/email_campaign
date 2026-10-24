"""Settings → Integrations: the workspace's intake webhook (Phase 6c)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import Services, require, services
from outbound.api.schemas import WebhookInfoOut, WebhookSecretOut
from outbound.domain.permissions import Permission as P

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
Svc = Annotated[Services, Depends(services)]


def _path(svc: Services) -> str:
    return f"/api/intake/webhook/{svc.workspace_id}"


MANAGE = [Depends(require(P.INTEGRATIONS_MANAGE))]


@router.get("/webhook", response_model=WebhookInfoOut, dependencies=MANAGE)
def webhook_info(svc: Svc) -> WebhookInfoOut:
    return WebhookInfoOut(path=_path(svc), configured=svc.webhook.configured())


@router.post("/webhook/rotate", response_model=WebhookSecretOut, dependencies=MANAGE)
def rotate_webhook_secret(svc: Svc) -> WebhookSecretOut:
    """A new secret, shown this once. Senders using the old one are refused from now on."""
    return WebhookSecretOut(path=_path(svc), secret=svc.webhook.rotate_secret())
