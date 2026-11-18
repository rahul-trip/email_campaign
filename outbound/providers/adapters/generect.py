"""Generect: email finder, billed only when a valid address is found.

Docs: https://docs.generect.com/api-reference/openapi.yaml (read 2026-11-18). ``POST
/api/v1/email/find/`` with ``first_name``, ``last_name`` and ``domain``; the key goes in
``Authorization: Token <key>``. The answer is ``{"data": {"valid_email": ..., "result": "valid",
"catch_all": false}, "meta": {"amount_charged": 0.02}}``; ``valid_email`` is null when nothing
was found (``amount_charged`` 0). 401 and 403 are a bad key; 402 is no credit (``BudgetExceeded``).
"""

from __future__ import annotations

import httpx

from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import FinderResult, PersonQuery

BASE_URL = "https://api.generect.com/api/v1"
_CONFIDENCE = 0.9  # the vendor calls it valid; a catch-all domain is settled by our own check


class GenerectFinder:
    name = "generect"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(
            self.name, BASE_URL, headers={"Authorization": f"Token {key}"}, client=client
        )

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        payload = self._http.post_object(
            "/email/find/",
            {"first_name": person.first_name, "last_name": person.last_name, "domain": domain},
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        address = str((data or {}).get("valid_email") or "").strip().lower()
        said = str((data or {}).get("result") or "").lower()
        found = bool(address) and said in ("", "valid")
        charged = (meta or {}).get("amount_charged")
        return FinderResult(
            email=address if found else None,
            provider=self.name,
            confidence=_CONFIDENCE if found else None,
            raw_status=said or ("valid" if found else "not_found"),
            billed=found and (bool(charged) if charged is not None else True),
        )
