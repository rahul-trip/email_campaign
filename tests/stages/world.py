"""Fake vendors for end-to-end tests: a whole engine with only the outside world replaced."""

from __future__ import annotations

from outbound.pipeline import Providers
from outbound.providers.ports import (
    FinderResult,
    PageText,
    PersonQuery,
    VerificationResult,
    VerificationStatus,
)
from tests.stages.fakes import FakeLlm, FakeMailbox, FakeRegistry, FakeSearch

PROFILE = {
    "company_name": "Quantra",
    "narrative": "We forecast renewable output.",
    "value_propositions": ["Cuts forecast error 20-35%"],
    "signature_name": "Sam Lee",
    "signature_title": "CPO, Quantra",
    "legal_name": "Quantra Energy Ltd",
    "postal_address": "1 Main St, Leeds",
    "registration_details": "Company no. 99999999",
    "contact_info": "sam@quantra.example",
}


class SiteSearch(FakeSearch):
    """Every site has a team page naming Jane Doe, and a footer that shows its legal form."""

    def extract(self, urls: list[str]) -> list[PageText]:
        self.extracted.append(urls)
        domain = urls[0].split("//")[1]
        return [
            PageText(url=f"https://{domain}", text=f"{domain} builds grid forecasting software."),
            PageText(
                url=f"https://{domain}/team",
                text="Our leadership team. Jane Doe is our Chief Technology Officer and leads "
                "the engineering group, with twenty years in energy software and data.",
            ),
            PageText(
                url=f"https://{domain}/contact",
                text=f"{domain} Ltd. Registered in England and Wales. Company number 01234567.",
            ),
        ]


class AutoFinder:
    name = "finder"

    def __init__(self) -> None:
        self.calls = 0

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        self.calls += 1
        address = f"{person.first_name}.{person.last_name}@{domain}".lower()
        return FinderResult(email=address, provider=self.name)


class AllValid:
    name = "verifier"

    def __init__(self) -> None:
        self.calls = 0

    def verify(self, email: str) -> VerificationResult:
        self.calls += 1
        return VerificationResult(email=email, status=VerificationStatus.VALID, provider=self.name)


class World:
    """Everything the pipeline talks to, kept so a test can look at what was used."""

    def __init__(self) -> None:
        self.search = SiteSearch()
        self.llm = FakeLlm()
        self.finder = AutoFinder()
        self.verifier = AllValid()
        self.mailbox = FakeMailbox()
        self.registry = FakeRegistry([])

    def providers(self) -> Providers:
        return Providers(
            search=self.search,
            llm=self.llm,
            finders=[self.finder],
            verifier=self.verifier,
            registry=self.registry,
            mailbox=self.mailbox,
        )
