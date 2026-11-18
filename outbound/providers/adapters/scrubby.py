"""Scrubby: asynchronous catch-all resolver, by its deep verification.

Docs: https://docs.scrubby.io, whose OpenAPI file is https://docs.scrubby.io/scrubby-openapi.json
(read 2026-11-16). The key goes in the ``x-api-key`` header. Deep verification is the part of
Scrubby that settles an address on a catch-all domain: ``POST /validate_bulk_emails/deep/`` with
``{"email": [address]}`` queues it and returns an ``identifier``; ``POST /fetch_bulk_results/deep``
with that identifier says ``processing`` until the batch is ``completed``. Its answer comes in
three windows, ``results_24``, ``results_48`` and ``results_72``, each mapping an address to
``Valid``, ``Invalid``, ``Risky``, ``Unknown`` or ``pending``; the batch is ``completed`` once
all three are final, about 72 hours after the submit (``retry_after_seconds`` says 259200). The
latest final window is the answer. It costs more credits per address than a plain check.

A plain ``results`` map belongs to the quick bulk check (``/fetch_bulk_results``). This adapter
read only that map until 2026-11-18, so a completed deep batch had no answer for the address and
every catch-all would have ended unproven (R-48, seen in a live poll).

The first version of this adapter used ``POST /add_email`` and ``GET /fetch_email/{email}``, which
the API does not have: every submit was a 404 and every catch-all lead ended unproven.
"""

from __future__ import annotations

import httpx

from outbound.providers.errors import ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import ResolutionResult, ResolutionStatus, ResolutionTicket

BASE_URL = "https://api.scrubby.io"
_VALID = {"valid"}
_INVALID = {"invalid"}
# Latest first: a later window has watched the address for longer. ``results`` is the quick
# check's map, kept for an answer in that shape.
_WINDOWS = ("results_72", "results_48", "results_24", "results")


class ScrubbyResolver:
    name = "scrubby"

    def __init__(
        self, api_key: str, base_url: str = BASE_URL, *, client: httpx.Client | None = None
    ) -> None:
        key = require_api_key(self.name, api_key)
        # Its bulk submit answers 202 Accepted: that is success, and asking again would queue
        # (and charge for) the batch a second time.
        self._http = HttpClient(
            self.name,
            base_url or BASE_URL,
            headers={"x-api-key": key},
            client=client,
            accepted_is_final=True,
        )

    def submit(self, email: str) -> ResolutionTicket:
        """Queue the address for deep verification. The answer never comes with it."""
        payload = self._http.post_object("/validate_bulk_emails/deep/", {"email": [email]})
        identifier = str(payload.get("identifier") or "")
        if not identifier:
            raise ProviderError(self.name, "the batch was accepted but no identifier came back")
        return ResolutionTicket(ref=identifier, email=email, provider=self.name)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        payload = self._http.post_object("/fetch_bulk_results/deep", {"identifier": ticket.ref})
        if str(payload.get("status") or "processing").strip().lower() != "completed":
            return None
        raw = _verdict(payload, ticket.email)
        if raw == "pending":
            return None
        if raw in _VALID:
            status = ResolutionStatus.VALID
        elif raw in _INVALID:
            status = ResolutionStatus.INVALID
        else:  # Risky, Unknown, or nothing for this address
            status = ResolutionStatus.UNRESOLVED
        return ResolutionResult(
            email=ticket.email, status=status, provider=self.name, raw_status=raw
        )


def _verdict(payload: dict[str, object], email: str) -> str:
    """The latest final word on ``email`` across the windows: ``pending`` while any window that
    holds the address still waits and none has answered, ``unknown`` when none holds it."""
    seen_pending = False
    for window in _WINDOWS:
        results = payload.get(window)
        if not isinstance(results, dict):
            continue
        item = next(
            (
                v
                for k, v in results.items()
                if str(k).lower() == email.lower() and isinstance(v, dict)
            ),
            None,
        )
        if item is None:
            continue
        raw = str(item.get("result") or "unknown").strip().lower()
        if raw == "pending":
            seen_pending = True
            continue
        return raw
    return "pending" if seen_pending else "unknown"
