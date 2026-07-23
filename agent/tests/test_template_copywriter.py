"""agent/tests/test_template_copywriter.py — TemplateCopywriter unit tests."""

from __future__ import annotations

from agent.config.models import SenderProfile
from agent.domain.models import Company, Contact
from agent.providers.copywriter.template_stub import TemplateCopywriter, _matching_technologies

COMPANY = Company(name="Renewco", domain="renewco.io", url="https://renewco.io",
                   description="Renewable energy machine learning forecasting for grid operators")
CONTACT = Contact(full_name="Alice Tester", title="VP of Sales")


class FakeConfig:
    signature_name = "Test User"
    signature_title = "CPO"
    sender = SenderProfile(
        company_name="TestCo",
        industry="Testing",
        mission="We test things.",
        value_propositions=("Fast ML forecasting", "Great support"),
        technologies=("machine learning", "grid optimization"),
    )


def test_output_uses_sender_company_name_not_hardcoded():
    cw = TemplateCopywriter()
    result = cw.write(COMPANY, CONTACT, FakeConfig())
    assert "TestCo" in result.pitch_email
    assert "Quantra" not in result.pitch_email
    assert "Quantra" not in result.follow_up
    assert "Quantra" not in result.commonalities


def test_output_contains_no_banned_phrases():
    cw = TemplateCopywriter()
    result = cw.write(COMPANY, CONTACT, FakeConfig())
    lowered = result.pitch_email.lower()
    assert "hope this finds you well" not in lowered
    assert "i wanted to reach out" not in lowered
    assert "touch base" not in lowered


def test_matching_technologies_finds_overlap():
    hits = _matching_technologies(("machine learning", "blockchain"), "We do machine learning research")
    assert hits == ["machine learning"]


def test_matching_technologies_no_overlap_returns_empty():
    hits = _matching_technologies(("blockchain",), "We do machine learning research")
    assert hits == []


def test_commonalities_fallback_when_no_tech_match():
    cw = TemplateCopywriter()

    class NoMatchConfig(FakeConfig):
        sender = SenderProfile(company_name="TestCo", industry="", technologies=("blockchain",))

    result = cw.write(COMPANY, CONTACT, NoMatchConfig())
    assert result.commonalities.strip() != ""
