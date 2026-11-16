from __future__ import annotations

import json
from typing import Any

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


def finished(body: dict[str, Any]) -> Handler:
    """A submit that is accepted, then a poll that answers ``body``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/deep/"):
            return respond("scrubby/add_pending.json")
        return httpx.Response(200, json=body)

    return handler


class TestScrubbyResolver(CatchAllResolverContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> ScrubbyResolver:
        return ScrubbyResolver(api_key, BASE_URL, client=mock_client(handler))

    def ok_response(self) -> httpx.Response:
        return respond("scrubby/add_pending.json")

    def scenario(self, status: ResolutionStatus | None) -> Handler:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/deep/"):
                return respond("scrubby/add_pending.json")
            return respond(_FETCH_BY_STATUS[status])

        return handler

    def test_submit_never_carries_a_result_because_deep_verification_takes_up_to_a_day(
        self,
    ) -> None:
        ticket = self.build(self.scenario(ResolutionStatus.VALID)).submit(EMAIL)
        assert ticket.result is None
        assert ticket.ref == "2fbf182d25594091a2ab66a37bbe9f4d"  # the batch, not the address

    def test_risky_and_unknown_are_unresolved_never_valid(self) -> None:
        for word in ("Risky", "Unknown"):
            body = {"status": "completed", "results": {EMAIL: {"result": word}}}
            adapter = self.build(finished(body))
            result = adapter.poll(adapter.submit(EMAIL))
            assert result is not None and result.status is ResolutionStatus.UNRESOLVED

    def test_a_finished_batch_with_no_answer_for_the_address_is_unresolved(self) -> None:
        adapter = self.build(finished({"status": "completed", "results": {}}))
        result = adapter.poll(adapter.submit(EMAIL))
        assert result is not None and result.status is ResolutionStatus.UNRESOLVED

    def test_the_address_is_found_in_the_results_whatever_its_case(self) -> None:
        body = {"status": "completed", "results": {EMAIL.upper(): {"result": "Valid"}}}
        adapter = self.build(finished(body))
        result = adapter.poll(adapter.submit(EMAIL))
        assert result is not None and result.status is ResolutionStatus.VALID

    def test_a_batch_accepted_without_an_identifier_is_an_error(self) -> None:
        adapter = self.build(always(httpx.Response(200, json={"status": "processing"})))
        with pytest.raises(ProviderError, match="identifier"):
            adapter.submit(EMAIL)

    def test_requests_follow_the_documented_routes_bodies_and_header(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond(
                "scrubby/add_pending.json"
                if request.url.path.endswith("/deep/")
                else "scrubby/fetch_pending.json"
            )

        adapter = self.build(handler)
        adapter.poll(adapter.submit("jane+tag@acme.com"))
        submit, fetch = seen
        assert submit.method == "POST" and submit.url.path == "/api/validate_bulk_emails/deep/"
        assert json.loads(submit.content) == {"email": ["jane+tag@acme.com"]}
        assert submit.headers["x-api-key"] == SECRET
        assert fetch.method == "POST" and fetch.url.path == "/api/fetch_bulk_results/deep"
        assert json.loads(fetch.content) == {"identifier": "2fbf182d25594091a2ab66a37bbe9f4d"}

    def test_without_a_base_url_the_documented_address_is_used(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("scrubby/add_pending.json")

        ScrubbyResolver(SECRET, "", client=mock_client(handler)).submit(EMAIL)
        assert seen[0].url.host == "api.scrubby.io"


def test_a_202_on_submit_is_success_and_is_never_asked_again_so_it_is_billed_once() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(202, json={"status": "processing", "identifier": "batch-1"})

    ticket = ScrubbyResolver(SECRET, BASE_URL, client=mock_client(handler)).submit(EMAIL)
    assert ticket.ref == "batch-1"
    assert len(sent) == 1  # a retry would submit, and charge for, the batch again
