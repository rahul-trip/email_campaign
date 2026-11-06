from __future__ import annotations

import base64

import httpx

from outbound.providers.adapters.companies_house import CompaniesHouse
from outbound.providers.ports import RegistryEntry, SourceQuery
from tests.contract._shared import SECRET, AdapterContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestCompaniesHouse(AdapterContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> CompaniesHouse:
        return CompaniesHouse(api_key, client=mock_client(handler))

    def call(self, adapter: CompaniesHouse) -> list[RegistryEntry]:
        return adapter.search("Acme Energy")

    def ok_response(self) -> httpx.Response:
        return respond("companies_house/search.json")

    def test_entries_are_mapped_and_rows_without_a_number_are_skipped(self) -> None:
        entries = self.call(self.build(always(self.ok_response())))
        assert [e.number for e in entries] == ["01234567", "07654321"]
        first = entries[0]
        assert (first.name, first.status, first.company_type) == (
            "ACME ENERGY LIMITED",
            "active",
            "ltd",
        )
        assert first.address.startswith("1 High Street")
        assert entries[1].address == ""

    def test_sends_the_api_key(self) -> None:
        """Overrides the shared check: the key is base64-encoded inside HTTP Basic auth."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.ok_response()

        self.build(handler).search("Acme Energy", max_results=500)
        token = seen[0].headers["authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == f"{SECRET}:"
        assert seen[0].url.params["q"] == "Acme Energy"
        assert seen[0].url.params["items_per_page"] == "20"

    def test_no_match_is_an_empty_list(self) -> None:
        empty = httpx.Response(200, json={"items": [], "total_results": 0})
        assert self.call(self.build(always(empty))) == []


# ------------------------------------------------------------------ finding companies by industry


def finder(seen: list[httpx.Request]) -> CompaniesHouse:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond("companies_house/advanced_search.json")

    return CompaniesHouse(SECRET, client=mock_client(handler))


def test_active_uk_companies_are_found_by_industry_code_and_founding_year() -> None:
    seen: list[httpx.Request] = []
    query = SourceQuery(industry_codes=("35110", "35120"), founded_after=2010)
    found = finder(seen).find(query, limit=30)
    params = seen[0].url.params
    assert seen[0].url.path == "/advanced-search/companies"
    assert params["sic_codes"] == "35110,35120"
    assert params["company_status"] == "active"
    assert params["company_type"] == "ltd,plc,llp"  # companies PECR lets us email
    assert params["incorporated_from"] == "2010-01-01"
    assert params["size"] == "30"
    assert [m.name for m in found] == ["Northgrid Forecasting Ltd", "Severn Power plc"]
    first = found[0]
    assert first.domain is None  # the register has no websites
    assert (first.source, first.country, first.founded) == ("companies_house", "GB", 2019)
    assert first.source_url.endswith("/company/12345678")
    assert "SIC 35110, 62012" in first.evidence and "Leeds" in first.evidence


def test_without_industry_codes_the_register_is_not_asked() -> None:
    seen: list[httpx.Request] = []
    assert finder(seen).find(SourceQuery(keywords=("grid",)), limit=10) == []
    assert seen == []
