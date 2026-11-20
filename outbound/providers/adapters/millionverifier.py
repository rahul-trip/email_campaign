"""MillionVerifier: real-time email verifier, paid by the pack with credits that do not expire.

Docs: https://developer.millionverifier.com/ and
https://github.com/hubuco/millionverifier-real-time-api-v3 (read 2026-11-20).
``GET https://api.millionverifier.com/api/v3/?api=KEY&email=...&timeout=20`` answers a flat
object whose ``result`` is ``ok``, ``catch_all``, ``unknown``, ``disposable``, ``invalid`` or
``error``. The key travels as a query parameter, so no URL is ever put in an error message.

An error is told in the body, not by the HTTP status: ``result: "error"`` with the reason in
``error`` (``"Apikey not found"`` for a bad key). The other reasons are not documented word for
word, so the text is matched loosely: a key problem, no credits, or anything else.

Billing (its help centre): ``ok``, ``invalid`` and ``disposable`` cost a credit; ``catch_all``
and ``unknown`` do not, under a goodwill programme the vendor may end. A repeat of the same
address is charged again, so the meter's cache matters. ``credits`` in the answer is the balance
left, not what the call cost.
"""

from __future__ import annotations

import httpx

from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import VerificationResult, VerificationStatus

BASE_URL = "https://api.millionverifier.com/api/v3"
_VENDOR_TIMEOUT_SECONDS = 20  # how long it waits for the recipient's server: 2 to 60

_RESULT_MAP = {
    "ok": VerificationStatus.VALID,
    "catch_all": VerificationStatus.CATCH_ALL,
    "unknown": VerificationStatus.UNKNOWN,
    "disposable": VerificationStatus.INVALID,
    "invalid": VerificationStatus.INVALID,
}
_CHARGED = {"ok", "disposable", "invalid"}


class MillionVerifierVerifier:
    name = "millionverifier"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._api_key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, BASE_URL, client=client)

    def verify(self, email: str) -> VerificationResult:
        payload = self._http.get_object(
            "/", {"api": self._api_key, "email": email, "timeout": _VENDOR_TIMEOUT_SECONDS}
        )
        raw = str(payload.get("result") or "unknown").strip().lower()
        if raw == "error":
            raise self._error(str(payload.get("error") or ""))
        return VerificationResult(
            email=email,
            status=_RESULT_MAP.get(raw, VerificationStatus.UNKNOWN),
            provider=self.name,
            raw_status=raw,
            billed=raw in _CHARGED,
        )

    def _error(self, reason: str) -> ProviderError:
        said = reason.lower()
        if "apikey" in said or "api key" in said or "blocked" in said:
            return ProviderAuthError(self.name, "the vendor refused the key", status_code=401)
        if "credit" in said:
            return BudgetExceeded(self.name, "the account is out of credits")
        return ProviderError(self.name, f"the check failed: {reason[:80] or 'no reason given'}")
