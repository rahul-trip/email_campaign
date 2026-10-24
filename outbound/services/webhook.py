"""The signed intake webhook: other systems (a CRM, a form) can push targets in.

A request is trusted only if its HMAC-SHA256 signature over ``timestamp.body`` matches and the
timestamp is within five minutes, which also stops a captured request being replayed later.
Within that window the sender's event id makes delivery idempotent: sending the same event
twice changes nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import INTEGRATION_WEBHOOK
from outbound.domain.enums import CompanySource, CredentialPurpose, ImportSource
from outbound.services.intake import IntakeReport, IntakeService

TOLERANCE_SECONDS = 300
CREDENTIAL = "intake_webhook"  # the name of the workspace's signing secret
MAX_TARGETS = 200


class WebhookError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def sign(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(
    secret: str,
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    *,
    now: float | None = None,
) -> None:
    if not secret:
        raise WebhookError(503, "webhook_disabled", "The intake webhook has no secret configured.")
    if not signature or not timestamp:
        raise WebhookError(401, "bad_signature", "Signature and timestamp headers are required.")
    try:
        sent_at = float(timestamp)
    except ValueError:
        raise WebhookError(401, "bad_signature", "The timestamp is not a number.") from None
    if abs((time.time() if now is None else now) - sent_at) > TOLERANCE_SECONDS:
        raise WebhookError(401, "stale_timestamp", "The request is too old or from the future.")
    if not hmac.compare_digest(signature, sign(secret, timestamp, body)):
        raise WebhookError(401, "bad_signature", "The signature does not match.")


@dataclass(frozen=True)
class WebhookResult:
    duplicate: bool
    report: IntakeReport | None = None


class WebhookService:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, workspace_id: str, intake: IntakeService
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._intake = intake

    def configured(self) -> bool:
        with self._uow(self._workspace_id) as uow:
            return uow.credentials.get(CREDENTIAL) is not None

    def rotate_secret(self) -> str:
        """A new signing secret, shown once; the old one stops working at once."""
        secret = "whsec_" + secrets.token_urlsafe(32)
        with self._uow(self._workspace_id) as uow:
            uow.credentials.put(CREDENTIAL, CredentialPurpose.INTAKE_WEBHOOK, secret)
            uow.commit()
        return secret

    def receive(self, payload: Mapping[str, Any]) -> WebhookResult:
        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            raise WebhookError(422, "missing_event_id", "The payload needs an event_id.")
        rows = _targets(payload)
        label = f"webhook:{event_id}"[:500]
        with self._uow(self._workspace_id) as uow:
            if uow.imports.batch_exists(ImportSource.WEBHOOK, label):
                return WebhookResult(duplicate=True)
        try:
            report = self._intake.run(
                rows,
                source=ImportSource.WEBHOOK,
                company_source=CompanySource.MANUAL,
                filename=label,
                actor=INTEGRATION_WEBHOOK,
            )
        except IntegrityError:
            # Another delivery of the same event won the race and committed first.
            return WebhookResult(duplicate=True)
        return WebhookResult(duplicate=False, report=report)


def _targets(payload: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    targets = payload.get("targets")
    if isinstance(targets, list):
        rows = [t for t in targets if isinstance(t, dict)]
    else:
        rows = [{k: v for k, v in payload.items() if k != "event_id"}]
    if not rows or len(rows) > MAX_TARGETS:
        raise WebhookError(422, "bad_targets", f"Send between 1 and {MAX_TARGETS} targets.")
    return rows


def secret_of(uow_factory: UnitOfWorkFactory, workspace_id: str) -> str:
    """The workspace's signing secret, or "" when it has none (or there is no such workspace:
    the two cannot be told apart from outside)."""
    with uow_factory(workspace_id) as uow:
        if uow.credentials.get(CREDENTIAL) is None:
            return ""
        return uow.credentials.reveal(CREDENTIAL)[1]
