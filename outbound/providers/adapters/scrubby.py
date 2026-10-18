"""Scrubby: asynchronous catch-all resolver.

Docs: https://docs.scrubby.io (a JavaScript reference that could not be read in full).

WRITTEN FROM A PARTIAL REFERENCE. What the public docs confirm: the ``x-api-key`` header,
``POST /add_email`` to submit, ``GET /fetch_email/{email}`` to fetch, a ``pending`` status
while it works, and a limit of 10 requests a second. What they do not state, and the Phase 0
bake-off must confirm with a live key before this adapter is trusted:

* the API base URL (so ``base_url`` is required and has no default);
* the ``POST /add_email`` request body (assumed to be ``{"email": ...}``);
* the final result values (the web app shows Valid, Recovered, Invalid and Catch-All).
Validation takes 24 to 72 hours, so ``submit`` never carries a result.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from outbound.providers.errors import ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import ResolutionResult, ResolutionStatus, ResolutionTicket

_PENDING = {"pending", "processing", "queued", "in_progress"}
_VALID = {"valid", "recovered", "safe", "deliverable"}
_INVALID = {"invalid", "reject", "rejected", "undeliverable"}


class ScrubbyResolver:
    name = "scrubby"

    def __init__(self, api_key: str, base_url: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        if not base_url:
            raise ProviderError(self.name, "base_url is required (set SCRUBBY_BASE_URL)")
        self._http = HttpClient(self.name, base_url, headers={"x-api-key": key}, client=client)

    def submit(self, email: str) -> ResolutionTicket:
        self._http.post_object("/add_email", {"email": email})
        return ResolutionTicket(ref=email, email=email, provider=self.name)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        payload = self._http.get_object(f"/fetch_email/{quote(ticket.ref, safe='@')}")
        raw = str(payload.get("status") or "pending").strip().lower()
        if raw in _PENDING:
            return None
        if raw in _VALID:
            status = ResolutionStatus.VALID
        elif raw in _INVALID:
            status = ResolutionStatus.INVALID
        else:
            status = ResolutionStatus.UNRESOLVED
        return ResolutionResult(
            email=ticket.email, status=status, provider=self.name, raw_status=raw
        )
