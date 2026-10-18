"""Contract for the EmailVerifier port. Subclass and map each status to a vendor response."""

from __future__ import annotations

import httpx
import pytest

from outbound.providers.ports import EmailVerifier, VerificationResult, VerificationStatus
from tests.contract._shared import AdapterContract
from tests.providers.helpers import always

EMAIL = "jane@acme.com"


class EmailVerifierContract(AdapterContract):
    #: Vendor response for each status the vendor can express.
    responses: dict[VerificationStatus, httpx.Response]

    def make_responses(self) -> dict[VerificationStatus, httpx.Response]:
        raise NotImplementedError

    def ok_response(self) -> httpx.Response:
        return self.make_responses()[VerificationStatus.VALID]

    def call(self, adapter: EmailVerifier) -> VerificationResult:
        return adapter.verify(EMAIL)

    @pytest.mark.parametrize("status", list(VerificationStatus))
    def test_each_vendor_answer_maps_to_the_port_status(self, status: VerificationStatus) -> None:
        responses = self.make_responses()
        if status not in responses:
            pytest.skip(f"{type(self).__name__} cannot express {status.value}")
        adapter = self.build(always(responses[status]))
        result = self.call(adapter)
        assert result.status is status
        assert result.email == EMAIL
        assert result.provider == adapter.name
