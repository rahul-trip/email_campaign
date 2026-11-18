"""Icypeas: email finder, one credit per address found.

Docs: https://api-doc.icypeas.com/reference/email-search and ``/reference/get-results`` (read
2026-11-18). A search is asynchronous: ``POST https://app.icypeas.com/api/email-search`` with
``firstname``, ``lastname`` and ``domainOrCompany`` answers ``{"success": true, "item":
{"_id": ..., "status": "NONE"}}``; the result is read with ``POST /api/bulk-single-searchs/read``
``{"id": ...}``, which answers ``{"items": [{"status": ..., "results": {"emails": [{"email": ...,
"certainty": ...}]}}]}``. The key goes in ``Authorization`` as it is. Reads are limited to 30 a
minute, so they are 3 seconds apart; a search that has not finished in about 25 seconds is an
error (the lead waits and is tried again), not "nothing found". Validation errors come as HTTP 200
with ``success: false``; no credit is the result status ``INSUFFICIENT_FUNDS``.
Certainty: ``ultra_sure`` and ``very_sure`` (about 99%) and ``probable`` (about 95%) are taken;
``undeliverable`` and ``not_found`` are not. Every address is still verified by our own check.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import FinderResult, PersonQuery

BASE_URL = "https://app.icypeas.com/api"
POLL_EVERY_SECONDS = 3.0
MAX_POLLS = 8
_PENDING = {"", "NONE", "SCHEDULED", "IN_PROGRESS", "PENDING"}
_TAKEN = {"ultra_sure": 0.99, "very_sure": 0.97, "probable": 0.9}  # best first


class IcypeasFinder:
    name = "icypeas"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        polls: int = MAX_POLLS,
        every: float = POLL_EVERY_SECONDS,
    ) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, BASE_URL, headers={"Authorization": key}, client=client)
        self._sleep, self._polls, self._every = sleep, polls, every

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        started = self._http.post_object(
            "/email-search",
            {
                "firstname": person.first_name,
                "lastname": person.last_name,
                "domainOrCompany": domain,
            },
        )
        item = started.get("item") if isinstance(started.get("item"), dict) else {}
        search_id = str((item or {}).get("_id") or "")
        if started.get("success") is False or not search_id:
            raise ProviderError(self.name, "the search was not accepted")
        for _ in range(self._polls):
            self._sleep(self._every)
            read = self._http.post_object("/bulk-single-searchs/read", {"id": search_id})
            items = read.get("items")
            row: dict[str, Any] = items[0] if isinstance(items, list) and items else {}
            status = str(row.get("status") or "").upper()
            if status in _PENDING:
                continue
            if status == "INSUFFICIENT_FUNDS":
                raise BudgetExceeded(self.name, "the account is out of credits")
            return self._answer(row, status)
        raise ProviderError(
            self.name, f"the search had not finished after {self._polls * self._every:g} seconds"
        )

    def _answer(self, row: dict[str, Any], status: str) -> FinderResult:
        emails = ((row.get("results") or {}).get("emails")) or []
        ranked = sorted(
            (e for e in emails if isinstance(e, dict) and str(e.get("certainty")) in _TAKEN),
            key=lambda e: -_TAKEN[str(e["certainty"])],
        )
        address = str(ranked[0].get("email") or "").strip().lower() if ranked else ""
        if not address:
            return FinderResult(
                email=None, provider=self.name, raw_status=status.lower() or "not_found",
                billed=False,
            )  # fmt: skip
        return FinderResult(
            email=address,
            provider=self.name,
            confidence=_TAKEN[str(ranked[0]["certainty"])],
            raw_status=str(ranked[0]["certainty"]),
        )
