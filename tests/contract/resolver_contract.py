"""Contract for the CatchAllResolver port.

``scenario`` returns a handler that answers every endpoint the way the vendor would when the
outcome is ``status``; ``None`` means the vendor is still working. The same checks then cover
both real-time resolvers (the answer comes with ``submit``) and asynchronous ones (``poll``).
"""

from __future__ import annotations

import pytest

from outbound.providers.ports import CatchAllResolver, ResolutionResult, ResolutionStatus
from tests.contract._shared import AdapterContract
from tests.providers.helpers import Handler

EMAIL = "jane@acme.com"


def resolve(adapter: CatchAllResolver) -> ResolutionResult | None:
    ticket = adapter.submit(EMAIL)
    return ticket.result if ticket.result is not None else adapter.poll(ticket)


class CatchAllResolverContract(AdapterContract):
    can_be_pending = True

    def scenario(self, status: ResolutionStatus | None) -> Handler:
        raise NotImplementedError

    # ``ok_response`` (used by the shared credential and failure checks) is supplied by the
    # subclass: any answer the vendor gives to a valid submit.

    def call(self, adapter: CatchAllResolver) -> ResolutionResult | None:
        return resolve(adapter)

    @pytest.mark.parametrize("status", list(ResolutionStatus))
    def test_each_outcome_maps_to_the_port_status(self, status: ResolutionStatus) -> None:
        adapter = self.build(self.scenario(status))
        result = resolve(adapter)
        assert result is not None
        assert result.status is status
        assert result.email == EMAIL
        assert result.provider == adapter.name

    def test_a_pending_vendor_gives_no_result_yet(self) -> None:
        if not self.can_be_pending:
            pytest.skip("real-time resolver: it never leaves a ticket pending")
        assert resolve(self.build(self.scenario(None))) is None

    def test_submit_returns_a_ticket_that_names_the_email(self) -> None:
        ticket = self.build(self.scenario(ResolutionStatus.VALID)).submit(EMAIL)
        assert ticket.email == EMAIL
        assert ticket.ref
