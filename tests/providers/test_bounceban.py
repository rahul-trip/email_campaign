from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.bounceban import BounceBanResolver
from outbound.providers.errors import BudgetExceeded, ProviderAuthError
from outbound.providers.ports import ResolutionStatus
from tests.contract._shared import SECRET
from tests.contract.resolver_contract import EMAIL, CatchAllResolverContract
from tests.providers.helpers import Handler, always, mock_client, respond

_BY_STATUS = {
    ResolutionStatus.VALID: "bounceban/single_deliverable.json",
    ResolutionStatus.INVALID: "bounceban/single_undeliverable.json",
    ResolutionStatus.UNRESOLVED: "bounceban/single_risky.json",
}


def _timed_out_then(fixture_name: str) -> Handler:
    """The check outlasts the call (HTTP 408 with its id); the status read answers later."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            return respond(fixture_name)
        return respond("bounceban/single_timeout.json", status=408)

    return handler


class TestBounceBanResolver(CatchAllResolverContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> BounceBanResolver:
        return BounceBanResolver(api_key, client=mock_client(handler))

    def ok_response(self) -> httpx.Response:
        return respond("bounceban/single_deliverable.json")

    def scenario(self, status: ResolutionStatus | None) -> Handler:
        if status is None:
            return _timed_out_then("bounceban/single_verifying.json")
        return always(respond(_BY_STATUS[status]))

    def test_an_answer_comes_with_submit_so_no_polling_is_needed(self) -> None:
        adapter = self.build(always(respond("bounceban/single_deliverable.json")))
        ticket = adapter.submit(EMAIL)
        assert ticket.result is not None
        assert adapter.poll(ticket) is ticket.result

    def test_unknown_stays_unresolved_and_risky_is_never_valid(self) -> None:
        unknown = self.build(always(respond("bounceban/single_unknown.json"))).submit(EMAIL)
        risky = self.build(always(respond("bounceban/single_risky.json"))).submit(EMAIL)
        assert unknown.result is not None and risky.result is not None
        assert unknown.result.status is ResolutionStatus.UNRESOLVED
        assert risky.result.status is ResolutionStatus.UNRESOLVED
        assert risky.result.raw_status == "risky"

    def test_billing_follows_credits_consumed(self) -> None:
        unknown = self.build(always(respond("bounceban/single_unknown.json"))).submit(EMAIL)
        valid = self.build(always(respond("bounceban/single_deliverable.json"))).submit(EMAIL)
        assert unknown.result is not None and unknown.result.billed is False
        assert valid.result is not None and valid.result.billed is True

    def test_a_check_that_outlasts_the_call_is_read_later_by_its_id(self) -> None:
        seen: list[httpx.Request] = []
        answer = _timed_out_then("bounceban/single_deliverable.json")

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return answer(request)

        adapter = self.build(handler)
        ticket = adapter.submit(EMAIL)
        assert ticket.result is None
        assert ticket.ref == "65f1c0a2b7e4d3001a9c0005"
        result = adapter.poll(ticket)
        assert result is not None and result.status is ResolutionStatus.VALID
        assert seen[-1].url.path.endswith("/v1/verify/single/status")
        assert seen[-1].url.params["id"] == ticket.ref

    def test_no_credits_is_a_budget_stop_not_a_refused_key(self) -> None:
        out = self.build(always(respond("bounceban/no_credits.json", status=403)))
        with pytest.raises(BudgetExceeded):
            out.submit(EMAIL)
        refused = self.build(always(httpx.Response(401, json={"msg": "Invalid API key."})))
        with pytest.raises(ProviderAuthError):
            refused.submit(EMAIL)

    def test_the_request_follows_the_docs(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("bounceban/single_deliverable.json")

        self.build(handler).submit(EMAIL)
        assert seen[0].method == "GET"
        assert seen[0].url.host == "api-waterfall.bounceban.com"
        assert seen[0].url.path == "/v1/verify/single"
        assert seen[0].url.params["email"] == EMAIL
        assert seen[0].url.params["timeout"] == "60"
        assert seen[0].headers["authorization"] == SECRET
