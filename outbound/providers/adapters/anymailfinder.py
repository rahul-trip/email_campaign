"""Anymail Finder: email finder, paid per address found.

Docs: https://anymailfinder.com/email-finder-api/docs/find-person-email (read 2026-11-18).
``POST /v5.1/find-email/person`` with the domain and the person's name; the key goes in the
``Authorization`` header as it is, with no ``Bearer``. A search answers HTTP 200 with
``email_status``: ``valid`` (one credit) or ``not_found`` / ``blacklisted`` (free; since
2026-10-05 a risky address is also ``not_found``). No credits is HTTP 402, which ``HttpClient``
reports as ``BudgetExceeded``; a bad key is 401. Searches repeated within 30 days are free.
The vendor documents no rate limit and recommends a long timeout for a search.
"""

from __future__ import annotations

from typing import Any

import httpx

from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import FinderResult, PersonQuery

BASE_URL = "https://api.anymailfinder.com/v5.1"
_TIMEOUT_SECONDS = 90.0  # most answer in about 3 seconds; the vendor advises waiting longer
_CONFIDENCE = 0.95  # "valid" is verified by the vendor before it is returned


class AnymailFinder:
    name = "anymailfinder"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(
            self.name, BASE_URL, headers={"Authorization": key}, timeout=_TIMEOUT_SECONDS,
            client=client,
        )  # fmt: skip

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        body: dict[str, Any] = {
            "domain": domain,
            "first_name": person.first_name,
            "last_name": person.last_name,
        }
        if person.linkedin_url:
            body["linkedin_url"] = person.linkedin_url
        payload = self._http.post_object("/find-email/person", body)
        status = str(payload.get("email_status") or "").lower()
        address = str(payload.get("valid_email") or payload.get("email") or "").strip().lower()
        found = status == "valid" and bool(address)  # only a verified address is taken
        charged = payload.get("credits_charged")
        return FinderResult(
            email=address if found else None,
            provider=self.name,
            confidence=_CONFIDENCE if found else None,
            raw_status=status,
            billed=found and (bool(charged) if charged is not None else True),
        )
