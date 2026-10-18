"""UK Companies House: is this name a registered company?

Docs: https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api
The key is sent as the user name of HTTP Basic auth with an empty password. The API is free and
limited to 600 requests every 5 minutes. Used to settle whether a UK lead is a corporate
subscriber (limited company, plc, LLP), which PECR lets us email, or something else.
"""

from __future__ import annotations

import base64

import httpx

from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import RegistryEntry

BASE_URL = "https://api.company-information.service.gov.uk"
_MAX_RESULTS = 20


class CompaniesHouse:
    name = "companies_house"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        token = base64.b64encode(f"{key}:".encode()).decode("ascii")
        self._http = HttpClient(
            self.name, BASE_URL, headers={"Authorization": f"Basic {token}"}, client=client
        )

    def search(self, company_name: str, *, max_results: int = 5) -> list[RegistryEntry]:
        payload = self._http.get_object(
            "/search/companies",
            {"q": company_name, "items_per_page": max(1, min(max_results, _MAX_RESULTS))},
        )
        return [
            RegistryEntry(
                name=item.get("title") or "",
                number=item["company_number"],
                status=item.get("company_status") or "",
                company_type=item.get("company_type") or "",
                address=item.get("address_snippet") or "",
            )
            for item in payload.get("items", [])
            if item.get("company_number")
        ]
