"""UK Companies House: is this name a registered company?

Docs: https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api
The key is sent as the user name of HTTP Basic auth with an empty password. The API is free and
limited to 600 requests every 5 minutes. Used to settle whether a UK lead is a corporate
subscriber (limited company, plc, LLP), which PECR lets us email, or something else.

It is also a discovery source (``find``): the advanced search lists active companies, plcs and
LLPs by industry (SIC) code and incorporation date. The register has no websites, so a company
found here becomes a lead only once its website is found.
"""

from __future__ import annotations

import base64

import httpx

from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import CompanyMention, RegistryEntry, SourceQuery

BASE_URL = "https://api.company-information.service.gov.uk"
_MAX_RESULTS = 20
_MAX_FOUND = 100
PROFILE_URL = "https://find-and-update.company-information.service.gov.uk/company/"
CORPORATE = "ltd,plc,llp"  # the corporate subscribers PECR lets us email


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

    def find(self, query: SourceQuery, *, limit: int) -> list[CompanyMention]:
        """Active UK companies in the query's industries, founded since its year if it has one.
        Nothing is asked without industry codes: the register cannot search by description."""
        if not query.industry_codes:
            return []
        params: dict[str, str | int] = {
            "sic_codes": ",".join(query.industry_codes),
            "company_status": "active",
            "company_type": CORPORATE,
            "size": max(1, min(limit, _MAX_FOUND)),
        }
        if query.founded_after:
            params["incorporated_from"] = f"{query.founded_after}-01-01"
        payload = self._http.get_object("/advanced-search/companies", params)
        return [m for item in payload.get("items", []) if (m := _mention(item))][:limit]


def _readable(name: str) -> str:
    """ "NORTHGRID FORECASTING LTD" as "Northgrid Forecasting Ltd"; a mixed-case name is kept."""
    return name.title() if name.isupper() else name


def _mention(item: dict[str, object]) -> CompanyMention | None:
    name = str(item.get("company_name") or "").strip()
    number = str(item.get("company_number") or "").strip()
    if not name or not number:
        return None
    created = str(item.get("date_of_creation") or "")
    year = int(created[:4]) if created[:4].isdigit() else None
    address = item.get("registered_office_address")
    town = str(address.get("locality") or "") if isinstance(address, dict) else ""
    raw_codes = item.get("sic_codes")
    codes = [str(c) for c in raw_codes] if isinstance(raw_codes, list) else []
    facts = [
        f"{item.get('company_type') or 'company'} registered in {town or 'the UK'}",
        f"incorporated {created}" if created else "",
        f"SIC {', '.join(codes)}" if codes else "",
    ]
    return CompanyMention(
        name=_readable(name),
        domain=None,
        description="; ".join(f for f in facts if f),
        tags=tuple(codes),
        country="GB",
        founded=year,
        source="companies_house",
        source_url=PROFILE_URL + number,
        evidence="Companies House: " + "; ".join(f for f in facts if f),
    )
