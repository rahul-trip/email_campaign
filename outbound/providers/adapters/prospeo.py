"""Prospeo: email finder (Enrich Person), paid per address found.

Docs: https://prospeo.io/api-docs/enrich-person (read 2026-11-18). ``POST /enrich-person`` with
``only_verified_email`` and the person's first name, last name and company website; the key goes
in the ``X-KEY`` header. A match carries ``person.email`` with a ``status`` (``VERIFIED``) and the
address. Prospeo answers HTTP 400 with an ``error_code`` for the cases that are not errors for
us: ``NO_MATCH`` (also when no verified address exists; free), ``INSUFFICIENT_CREDITS`` and
``INVALID_API_KEY``. One credit per address found; the same record again within 90 days is free.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import FinderResult, PersonQuery

BASE_URL = "https://api.prospeo.io"
_CONFIDENCE = 0.95  # VERIFIED: the vendor verified it (BounceBan) before returning it


def _error_code(text: str) -> str:
    try:
        body = json.loads(text)
    except ValueError:
        return ""
    return str(body.get("error_code") or "") if isinstance(body, dict) else ""


class ProspeoFinder:
    name = "prospeo"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, BASE_URL, headers={"X-KEY": key}, client=client)

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        body: dict[str, Any] = {
            "only_verified_email": True,
            "data": {
                "first_name": person.first_name,
                "last_name": person.last_name,
                "company_website": domain,
            },
        }
        try:
            payload = self._http.post_object("/enrich-person", body)
        except ProviderError as error:
            self._settle(_error_code(error.body), error)
            return self._miss("no_match")
        if payload.get("error"):  # an error body with HTTP 200
            self._settle(str(payload.get("error_code") or ""), None)
            return self._miss("no_match")
        shown = (payload.get("person") or {}).get("email") or {}
        address = str(shown.get("email") or "").strip().lower()
        status = str(shown.get("status") or "").upper()
        if status != "VERIFIED" or not address or "*" in address:  # a masked address is no use
            return self._miss(status.lower() or "no_match")
        return FinderResult(
            email=address, provider=self.name, confidence=_CONFIDENCE, raw_status="verified"
        )

    def _settle(self, code: str, error: ProviderError | None) -> None:
        """Raise for a code that is a real failure; return for one that means "nothing found"."""
        if code == "INSUFFICIENT_CREDITS":
            raise BudgetExceeded(self.name, "the account is out of credits") from None
        if code == "INVALID_API_KEY":
            raise ProviderAuthError(self.name, "the API key is not valid") from None
        if error is not None and code not in ("NO_MATCH", "NO_RESULT"):
            raise error  # some other 400 (a malformed request): a real error

    def _miss(self, raw: str) -> FinderResult:
        return FinderResult(email=None, provider=self.name, raw_status=raw, billed=False)
