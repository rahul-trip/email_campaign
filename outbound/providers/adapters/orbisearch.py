"""OrbiSearch: email verifier.

Docs: https://github.com/00al/orbisearch-api

OrbiSearch's public API has no email-finder endpoint (only verify, bulk and credits), so this
adapter is a verifier only. Its ``risky`` status means an unresolved catch-all. Repeat checks
of one address within 24 hours are free at the vendor.
"""

from __future__ import annotations

import httpx

from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import VerificationResult, VerificationStatus

BASE_URL = "https://api.orbisearch.com/v1"
_VENDOR_TIMEOUT_SECONDS = 25  # the vendor allows 3 to 90 seconds, default 70

_VERIFY_MAP = {
    "safe": VerificationStatus.VALID,
    "risky": VerificationStatus.CATCH_ALL,
    "invalid": VerificationStatus.INVALID,
    "unknown": VerificationStatus.UNKNOWN,
}


class OrbiSearchVerifier:
    name = "orbisearch"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, BASE_URL, headers={"X-API-Key": key}, client=client)

    def verify(self, email: str) -> VerificationResult:
        payload = self._http.get_json(
            "/verify", {"email": email, "timeout": _VENDOR_TIMEOUT_SECONDS}
        )
        status = str(payload.get("status") or "unknown").lower()
        substatus = payload.get("substatus")
        return VerificationResult(
            email=email,
            status=_VERIFY_MAP.get(status, VerificationStatus.UNKNOWN),
            provider=self.name,
            raw_status=f"{status}/{substatus}" if substatus else status,
        )
