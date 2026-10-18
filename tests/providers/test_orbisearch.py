from __future__ import annotations

import httpx
import pytest

from outbound.providers.adapters.orbisearch import OrbiSearchVerifier
from outbound.providers.errors import ProviderAuthError
from outbound.providers.ports import VerificationStatus
from tests.contract._shared import SECRET
from tests.contract.verifier_contract import EmailVerifierContract
from tests.providers.helpers import Handler, always, mock_client, respond


class TestOrbiSearchVerifier(EmailVerifierContract):
    def build(self, handler: Handler, api_key: str = SECRET) -> OrbiSearchVerifier:
        return OrbiSearchVerifier(api_key, client=mock_client(handler))

    def make_responses(self) -> dict[VerificationStatus, httpx.Response]:
        return {
            VerificationStatus.VALID: respond("orbisearch/verify_safe.json"),
            VerificationStatus.CATCH_ALL: respond("orbisearch/verify_risky.json"),
            VerificationStatus.INVALID: respond("orbisearch/verify_invalid.json"),
            VerificationStatus.UNKNOWN: respond("orbisearch/verify_unknown.json"),
        }

    def test_raw_status_keeps_the_substatus(self) -> None:
        result = self.build(always(respond("orbisearch/verify_risky.json"))).verify("a@b.com")
        assert result.raw_status == "risky/catch_all"

    def test_key_is_sent_in_the_x_api_key_header(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond("orbisearch/verify_safe.json")

        self.build(handler).verify("a@b.com")
        assert seen[0].headers["x-api-key"] == SECRET
        assert seen[0].url.params["email"] == "a@b.com"

    def test_insufficient_credits_is_reported_as_a_credential_problem(self) -> None:
        with pytest.raises(ProviderAuthError):
            self.build(always(httpx.Response(403))).verify("a@b.com")
