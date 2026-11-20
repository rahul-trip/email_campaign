"""BounceBan: catch-all resolver that answers within the call.

Docs: https://bounceban.com/public/doc/llms-full.txt (read 2026-11-20). The key goes in the
``Authorization`` header as it is, with no ``Bearer``. ``GET /v1/verify/single?email=`` on the
waterfall host (``api-waterfall.bounceban.com``) holds the connection until the address is
settled, up to ``timeout`` seconds (30 to 300), and answers ``status: "success"`` with a
``result``: ``deliverable``, ``undeliverable``, ``risky`` (may bounce) or ``unknown``. BounceBan
says it settles accept-all domains and ones behind a mail gateway without sending a message
(vendor claim, on its pricing page only; measure it with the bake-off).

When the time runs out it answers HTTP 408 with the verification's ``id``; the work goes on at
the vendor, and ``GET /v1/verify/single/status?id=`` (free) reads the answer later, so the
ticket then waits like an asynchronous resolver's. A repeat of the same address on this host
within 30 minutes is free. Each answer says what it cost in ``credits_consumed``.

HTTP 403 is "no credits left" or "this key's quota is used up", not a refused key (that is 401).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import ResolutionResult, ResolutionStatus, ResolutionTicket

BASE_URL = "https://api-waterfall.bounceban.com"
_VENDOR_TIMEOUT_SECONDS = 60  # the vendor allows 30 to 300, default 80
_CLIENT_TIMEOUT_SECONDS = 75.0  # longer than the vendor's, so its own 408 arrives first

_RESULT_MAP = {
    "deliverable": ResolutionStatus.VALID,
    "undeliverable": ResolutionStatus.INVALID,
    "risky": ResolutionStatus.UNRESOLVED,  # "may bounce": not proof enough to write to
    "unknown": ResolutionStatus.UNRESOLVED,
}


class BounceBanResolver:
    name = "bounceban"
    realtime = True  # the answer nearly always comes with the call

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(
            self.name, BASE_URL, headers={"Authorization": key}, timeout=_CLIENT_TIMEOUT_SECONDS,
            client=client,
        )  # fmt: skip

    def submit(self, email: str) -> ResolutionTicket:
        try:
            payload = self._ask(
                "/v1/verify/single", {"email": email, "timeout": _VENDOR_TIMEOUT_SECONDS}
            )
        except ProviderError as error:
            waiting = _id_of_a_timeout(error)
            if waiting is None:
                raise
            return ResolutionTicket(ref=waiting, email=email, provider=self.name)
        result = self._result(email, payload)
        ref = str(payload.get("id") or "")
        if result is None and not ref:
            raise ProviderError(self.name, "the check is still running but no id came back")
        return ResolutionTicket(ref=ref or email, email=email, provider=self.name, result=result)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        if ticket.result is not None:
            return ticket.result
        return self._result(ticket.email, self._ask("/v1/verify/single/status", {"id": ticket.ref}))

    def _ask(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._http.get_object(path, params)
        except ProviderAuthError as error:
            if error.status_code == 403:
                raise BudgetExceeded(
                    self.name, "the account or this key's quota is out of credits"
                ) from None
            raise

    def _result(self, email: str, payload: dict[str, Any]) -> ResolutionResult | None:
        """The settled answer, or None while the vendor says ``verifying`` or ``queue``."""
        if str(payload.get("status") or "").lower() != "success":
            return None
        raw = str(payload.get("result") or "unknown").lower()
        consumed = payload.get("credits_consumed")
        return ResolutionResult(
            email=email,
            status=_RESULT_MAP.get(raw, ResolutionStatus.UNRESOLVED),
            provider=self.name,
            raw_status=raw,
            billed=float(consumed) > 0 if isinstance(consumed, int | float) else True,
        )


def _id_of_a_timeout(error: ProviderError) -> str | None:
    """The verification id in a 408 answer: the check goes on and can be read later."""
    if error.status_code != 408:
        return None
    try:
        body = json.loads(error.body)
    except ValueError:
        return None
    found = str(body.get("id") or "") if isinstance(body, dict) else ""
    return found or None
