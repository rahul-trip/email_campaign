"""MyEmailVerifier: real-time email verifier.

Docs: https://github.com/pat-myemailverifier/myemailverifier-api

The public docs show a single example (``Status: "Valid"``) and do not list the other status
values, so the mapping is deliberately conservative: only an explicit ``valid`` with no
catch-all, greylist or disposable flag is VALID, and anything unrecognised is UNKNOWN. The
flags arrive as the strings ``"true"`` and ``"false"``.
"""

from __future__ import annotations

from typing import Any

import httpx

from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import VerificationResult, VerificationStatus

BASE_URL = "https://api.myemailverifier.com/api"


def _flag(payload: dict[str, Any], key: str) -> bool:
    return str(payload.get(key, "")).strip().lower() == "true"


class MyEmailVerifierVerifier:
    name = "myemailverifier"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._api_key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, BASE_URL, client=client)

    def verify(self, email: str) -> VerificationResult:
        payload = self._http.get_json(
            "/validate_single.php", {"apikey": self._api_key, "email": email}
        )
        raw = str(payload.get("Status") or "unknown").strip()
        return VerificationResult(
            email=email,
            status=self._classify(raw.lower(), payload),
            provider=self.name,
            raw_status=raw,
        )

    @staticmethod
    def _classify(status: str, payload: dict[str, Any]) -> VerificationStatus:
        if status in {"invalid", "spam trap", "spamtrap"} or _flag(payload, "Disposable_Domain"):
            return VerificationStatus.INVALID
        if status in {"catch-all", "catch all", "catchall"} or _flag(payload, "catch_all"):
            return VerificationStatus.CATCH_ALL
        if _flag(payload, "Greylisted"):
            return VerificationStatus.UNKNOWN
        if status == "valid":
            return VerificationStatus.VALID
        return VerificationStatus.UNKNOWN
