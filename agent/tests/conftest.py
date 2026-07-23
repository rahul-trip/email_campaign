"""agent/tests/conftest.py — Shared pytest fixtures.

Provides:
    - Fake in-memory providers (implement each ABC, return deterministic data)
    - A temporary copy of the campaign workbook for write-safety
    - A pre-built ProviderBundle of all fakes
    - A minimal AgentConfig for tests
"""

from __future__ import annotations

import shutil
from pathlib import Path

import openpyxl
import pytest

from agent.config.models import AgentConfig, LlmConfig, ProviderNames, SenderProfile
from agent.domain.models import COLUMN_ORDER, Company, Contact, Lead, VerifiedEmail
from agent.persistence.lead_repository import XlsxLeadRepository
from agent.providers.bundle import ProviderBundle
from agent.providers.contacts.base import ContactResolutionProvider
from agent.providers.copywriter.base import CopyOutput, CopywriterProvider
from agent.providers.discovery.base import CompanyDiscoveryProvider
from agent.providers.email_finder.base import EmailFinderProvider
from agent.providers.verifier.base import EmailVerifierProvider, VerificationStatus

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED_COMPANIES = [
    Company(name="Renewco", domain="renewco.io", url="https://renewco.io",
            description="Renewable energy analytics"),
    Company(name="GridLogic", domain="gridlogic.com", url="https://gridlogic.com",
            description="Grid optimization software"),
]

SEED_CONTACT = Contact(
    full_name="Alice Tester",
    title="VP of Sales",
    linkedin_url="https://linkedin.com/in/alicetester",
    eccentricities="Enthusiastic about renewables",
)


# ---------------------------------------------------------------------------
# Fake providers
# ---------------------------------------------------------------------------

class FakeDiscovery(CompanyDiscoveryProvider):
    def discover(self, keywords, location, limit):
        return SEED_COMPANIES[:limit]


class FakeContacts(ContactResolutionProvider):
    def resolve(self, company, target_titles):
        return SEED_CONTACT


class FakeEmailFinder(EmailFinderProvider):
    def find(self, company, contact):
        return f"alice@{company.domain}"


class FakeVerifier(EmailVerifierProvider):
    def verify(self, email):
        if "invalid" in email:
            return VerificationStatus.INVALID
        if "catchall" in email:
            return VerificationStatus.CATCHALL
        return VerificationStatus.VALID


class FakeCopywriter(CopywriterProvider):
    def write(self, company, contact, config):
        return CopyOutput(
            pitch_email=f"Hi {contact.full_name}, pitch for {company.name}.",
            follow_up=f"Following up on {company.name}.",
            commonalities=f"Both in energy sector; {company.name} aligns with Quantra.",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_bundle() -> ProviderBundle:
    return ProviderBundle(
        discovery=FakeDiscovery(),
        contacts=FakeContacts(),
        email_finder=FakeEmailFinder(),
        verifier=FakeVerifier(),
        copywriter=FakeCopywriter(),
    )


@pytest.fixture
def test_config(tmp_xlsx) -> AgentConfig:
    return AgentConfig(
        keywords=["solar energy"],
        location="UK",
        target_titles=["VP of Sales"],
        max_companies=5,
        max_leads=5,
        per_call_delay_seconds=0,
        providers=ProviderNames(
            discovery="tavily",
            contacts="brightdata",
            email_finder="hunter",
            verifier="neverbounce",
            copywriter="template",
        ),
        keep_statuses=["valid", "catchall", "unknown"],
        mark_risky_statuses=["catchall", "unknown"],
        xlsx_path=str(tmp_xlsx),
        run_drafts_after=False,
        signature_name="Test User",
        signature_title="CPO",
        sender=SenderProfile(
            company_name="TestCo",
            industry="Testing",
            mission="We test things.",
            value_propositions=("Fast, reliable test coverage",),
            technologies=("machine learning", "forecasting"),
            narrative="TestCo builds ML forecasting tools for the testing industry.",
        ),
        llm=LlmConfig(),
    )


@pytest.fixture
def tmp_xlsx(tmp_path) -> Path:
    """Create a minimal valid campaign matrix xlsx for tests."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(COLUMN_ORDER)  # header row
    # Seed one existing row so existing_domains() has something to return
    ws.append([
        "ExistingCo\nhttps://existingco.com",
        "Bob Smith\n(CTO)",
        "Loves sailing",
        "bob@existingco.com",
        "Hi Bob pitch",
        "Follow-up",
        "Common interests",
    ])
    path = tmp_path / "test_matrix.xlsx"
    wb.save(str(path))
    return path


@pytest.fixture
def repo(tmp_xlsx) -> XlsxLeadRepository:
    return XlsxLeadRepository(str(tmp_xlsx))


@pytest.fixture
def sample_lead() -> Lead:
    return Lead(
        company=SEED_COMPANIES[0],
        contact=SEED_CONTACT,
        email=VerifiedEmail(address="alice@renewco.io", status="valid", risky=False),
        pitch_email="Hi Alice, pitch.",
        follow_up="Following up.",
        commonalities="Both energy.",
    )
