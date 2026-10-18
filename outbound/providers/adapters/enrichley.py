"""Enrichley: real-time catch-all resolver.

Docs: https://docs.enrichley.io/api-reference/endpoint/email-validation.md

Enrichley checks the mailbox inside a catch-all domain without sending a test email, so the
answer comes back at once and the ticket already carries its result. ``catch_all`` (not
validated) and ``unknown`` mean it could not decide.
"""

from __future__ import annotations

import httpx

from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import ResolutionResult, ResolutionStatus, ResolutionTicket

BASE_URL = "https://api.enrichley.io/api/v1"

_RESULT_MAP = {
    "ok": ResolutionStatus.VALID,
    "catch_all_validated": ResolutionStatus.VALID,
    "invalid": ResolutionStatus.INVALID,
    "catch_all": ResolutionStatus.UNRESOLVED,
    "unknown": ResolutionStatus.UNRESOLVED,
}


class EnrichleyResolver:
    name = "enrichley"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, BASE_URL, headers={"X-Api-Key": key}, client=client)

    def submit(self, email: str) -> ResolutionTicket:
        payload = self._http.post_json("/validate-single-email", {"email": email})
        raw = str(payload.get("result") or "unknown")
        result = ResolutionResult(
            email=email,
            status=_RESULT_MAP.get(raw, ResolutionStatus.UNRESOLVED),
            provider=self.name,
            raw_status=raw,
            billed=bool(payload.get("credits_consumed", True)),
        )
        return ResolutionTicket(ref=email, email=email, provider=self.name, result=result)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        return ticket.result
