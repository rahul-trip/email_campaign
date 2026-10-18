from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.enrichley import EnrichleyResolver
from outbound.providers.ports import ResolutionStatus
from tests.contract._shared import SECRET
from tests.contract.resolver_contract import EMAIL, CatchAllResolverContract
from tests.providers.helpers import Handler, always, mock_client, respond

_BY_STATUS = {
    ResolutionStatus.VALID: "enrichley/validate_catch_all_validated.json",
    ResolutionStatus.INVALID: "enrichley/validate_invalid.json",
    ResolutionStatus.UNRESOLVED: "enrichley/validate_catch_all.json",
}


class TestEnrichleyResolver(CatchAllResolverContract):
    can_be_pending = False

    def build(self, handler: Handler, api_key: str = SECRET) -> EnrichleyResolver:
        return EnrichleyResolver(api_key, client=mock_client(handler))

    def ok_response(self) -> httpx.Response:
        return respond("enrichley/validate_ok.json")

    def scenario(self, status: ResolutionStatus | None) -> Handler:
        assert status is not None
        return always(respond(_BY_STATUS[status]))

    def test_an_answer_comes_with_submit_so_no_polling_is_needed(self) -> None:
        adapter = self.build(always(respond("enrichley/validate_catch_all_validated.json")))
        ticket = adapter.submit(EMAIL)
        assert ticket.result is not None
        assert adapter.poll(ticket) is ticket.result

    @pytest.mark.parametrize(
        ("fixture_name", "expected"),
        [
            ("enrichley/validate_ok.json", ResolutionStatus.VALID),
            ("enrichley/validate_unknown.json", ResolutionStatus.UNRESOLVED),
        ],
    )
    def test_ok_is_valid_and_unknown_stays_unresolved(
        self, fixture_name: str, expected: ResolutionStatus
    ) -> None:
        ticket = self.build(always(respond(fixture_name))).submit(EMAIL)
        assert ticket.result is not None
        assert ticket.result.status is expected

    def test_billing_follows_credits_consumed(self) -> None:
        unknown = self.build(always(respond("enrichley/validate_unknown.json"))).submit(EMAIL)
        valid = self.build(always(respond("enrichley/validate_ok.json"))).submit(EMAIL)
        assert unknown.result is not None and unknown.result.billed is False
        assert valid.result is not None and valid.result.billed is True

    def test_post_body_and_header_follow_the_docs(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("enrichley/validate_ok.json")

        self.build(handler).submit(EMAIL)
        assert seen[0].method == "POST"
        assert seen[0].url.path.endswith("/validate-single-email")
        assert seen[0].headers["x-api-key"] == SECRET
        assert seen[0].read() == b'{"email":"jane@acme.com"}'
