"""Contract for the EmailFinder port. Subclass and fill in the vendor's responses."""

from __future__ import annotations

import httpx

from outbound.providers.ports import EmailFinder, FinderResult, PersonQuery
from tests.contract._shared import AdapterContract
from tests.providers.helpers import always

PERSON = PersonQuery(first_name="Jane", last_name="Doe")
DOMAIN = "acme.com"


class EmailFinderContract(AdapterContract):
    expected_email = "jane.doe@acme.com"

    def found(self) -> httpx.Response:
        raise NotImplementedError

    def not_found(self) -> httpx.Response:
        raise NotImplementedError

    def ok_response(self) -> httpx.Response:
        return self.found()

    def call(self, adapter: EmailFinder) -> FinderResult:
        return adapter.find(PERSON, DOMAIN)

    def test_found_returns_a_lowercase_address_and_names_the_provider(self) -> None:
        adapter = self.build(always(self.found()))
        result = self.call(adapter)
        assert result.email == self.expected_email
        assert result.provider == adapter.name
        assert result.billed is True

    def test_nothing_found_is_a_result_not_an_error(self) -> None:
        result = self.call(self.build(always(self.not_found())))
        assert result.email is None
        assert result.billed is False
