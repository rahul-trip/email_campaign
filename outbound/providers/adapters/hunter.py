"""Hunter.io: email finder and email verifier.

Docs: https://hunter.io/api-documentation/v2

The key goes in the ``X-API-KEY`` header (Hunter accepts it there), which keeps it out of
URLs and logs. Hunter charges for a find only when it returns an address.
"""

from __future__ import annotations

from typing import Any

import httpx

from outbound.providers.errors import ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import (
    FinderResult,
    PersonQuery,
    VerificationResult,
    VerificationStatus,
)

BASE_URL = "https://api.hunter.io/v2"
_CLAIMED = 451  # the person asked Hunter to stop processing their data

# Hunter's verifier statuses. `webmail` is deliberately UNKNOWN: Hunter gives it an arbitrary
# score without proving the mailbox, and a free-mail address is not a business contact.
_VERIFY_MAP = {
    "valid": VerificationStatus.VALID,
    "invalid": VerificationStatus.INVALID,
    "disposable": VerificationStatus.INVALID,
    "accept_all": VerificationStatus.CATCH_ALL,
    "webmail": VerificationStatus.UNKNOWN,
    "unknown": VerificationStatus.UNKNOWN,
}


def _build_http(api_key: str, client: httpx.Client | None) -> HttpClient:
    key = require_api_key("hunter", api_key)  # checked even when a client is injected
    return HttpClient("hunter", BASE_URL, headers={"X-API-KEY": key}, client=client)


class HunterFinder:
    name = "hunter"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._http = _build_http(api_key, client)

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        params: dict[str, Any] = {
            "domain": domain,
            "first_name": person.first_name,
            "last_name": person.last_name,
        }
        try:
            payload = self._http.get_object("/email-finder", params)
        except ProviderError as exc:
            if exc.status_code == _CLAIMED:
                return FinderResult(
                    email=None, provider=self.name, raw_status="claimed_email", billed=False
                )
            raise
        data = payload.get("data") or {}
        email = (data.get("email") or "").strip().lower() or None
        score = data.get("score")
        return FinderResult(
            email=email,
            provider=self.name,
            confidence=score / 100 if isinstance(score, int | float) else None,
            raw_status=str((data.get("verification") or {}).get("status") or ""),
            billed=email is not None,
        )


class HunterVerifier:
    name = "hunter"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._http = _build_http(api_key, client)

    def verify(self, email: str) -> VerificationResult:
        try:
            payload = self._http.get_object("/email-verifier", {"email": email})
        except ProviderError as exc:
            if exc.status_code == _CLAIMED:
                return VerificationResult(
                    email=email,
                    status=VerificationStatus.INVALID,
                    provider=self.name,
                    raw_status="claimed_email",
                    billed=False,
                )
            raise
        raw = str((payload.get("data") or {}).get("status") or "unknown")
        return VerificationResult(
            email=email,
            status=_VERIFY_MAP.get(raw, VerificationStatus.UNKNOWN),
            provider=self.name,
            raw_status=raw,
        )
