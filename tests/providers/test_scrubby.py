from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.scrubby import ScrubbyResolver
from outbound.providers.errors import ProviderError
from outbound.providers.ports import ResolutionStatus
from tests.contract._shared import SECRET
from tests.contract.resolver_contract import EMAIL, CatchAllResolverContract
from tests.providers.helpers import Handler, always, mock_client, respond

BASE_URL = "https://scrubby.test/api"

_FETCH_BY_STATUS = {
    ResolutionStatus.VALID: "scrubby/fetch_valid.json",
    ResolutionStatus.INVALID: "scrubby/fetch_invalid.json",
    ResolutionStatus.UNRESOLVED: "scrubby/fetch_catch_all.json",
    None: "scrubby/fetch_pending.json",
}


class TestScrubbyResolver(CatchAllResolverContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> ScrubbyResolver:
        return ScrubbyResolver(api_key, BASE_URL, client=mock_client(handler))

    def ok_response(self) -> httpx.Response:
        return respond("scrubby/add_pending.json")

    def scenario(self, status: ResolutionStatus | None) -> Handler:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return respond("scrubby/add_pending.json")
            return respond(_FETCH_BY_STATUS[status])

        return handler

    def test_submit_never_carries_a_result_because_validation_takes_days(self) -> None:
        ticket = self.build(self.scenario(ResolutionStatus.VALID)).submit(EMAIL)
        assert ticket.result is None

    def test_recovered_counts_as_valid(self) -> None:
        recovered = httpx.Response(200, json={"email": EMAIL, "status": "Recovered"})
        adapter = self.build(always(recovered))
        result = adapter.poll(adapter.submit(EMAIL))
        assert result is not None and result.status is ResolutionStatus.VALID

    def test_an_unrecognised_final_status_is_unresolved_never_valid(self) -> None:
        odd = httpx.Response(200, json={"email": EMAIL, "status": "gibberish"})
        adapter = self.build(always(odd))
        result = adapter.poll(adapter.submit(EMAIL))
        assert result is not None and result.status is ResolutionStatus.UNRESOLVED

    def test_requests_follow_the_documented_routes_and_header(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("scrubby/fetch_pending.json")

        adapter = self.build(handler)
        adapter.poll(adapter.submit("jane+tag@acme.com"))
        post, get = seen
        assert post.method == "POST" and post.url.path.endswith("/add_email")
        assert post.headers["x-api-key"] == SECRET
        assert get.method == "GET" and str(get.url).endswith("/fetch_email/jane%2Btag@acme.com")

    def test_base_url_is_required_because_the_docs_do_not_state_one(self) -> None:
        with pytest.raises(ProviderError, match="base_url"):
            ScrubbyResolver(SECRET, "")
