"""agent/tests/test_nodes.py — Unit tests for individual LangGraph nodes.

Each node is tested in isolation with fake providers (no network, no disk).
"""

from __future__ import annotations

import logging

import pytest

from agent.domain.models import Company, Contact, Lead, VerifiedEmail
from agent.graph.nodes import (
    make_copy,
    make_discover,
    make_find,
    make_persist,
    make_resolve,
    make_sync,
    make_verify,
    route_after_discovery,
    route_after_verify,
)
from agent.providers.verifier.base import VerificationStatus
from .conftest import (
    SEED_COMPANIES,
    SEED_CONTACT,
    FakeContacts,
    FakeDiscovery,
    FakeEmailFinder,
    FakeCopywriter,
)

_LOG = logging.getLogger("agent")


# ---------------------------------------------------------------------------
# discover_companies
# ---------------------------------------------------------------------------

def test_discover_filters_known_domains(fake_bundle, test_config, repo):
    """Companies whose domain is already in the workbook must be filtered out."""
    # The fixture has "existingco.com" in the workbook.
    # Patch FakeDiscovery to also return that domain.
    from agent.providers.discovery.base import CompanyDiscoveryProvider
    from agent.domain.models import Company

    class DiscoveryWithExisting(CompanyDiscoveryProvider):
        def discover(self, keywords, location, limit):
            return [
                Company("ExistingCo", "existingco.com", "https://existingco.com"),
                Company("Renewco", "renewco.io", "https://renewco.io"),
            ]

    bundle = fake_bundle
    object.__setattr__(bundle, "discovery", DiscoveryWithExisting())
    node = make_discover(bundle, repo, _LOG)
    result = node({"config": test_config})

    companies = result["companies"]
    domains = [c.domain for c in companies]
    assert "existingco.com" not in domains
    assert "renewco.io" in domains


def test_discover_returns_step_log(fake_bundle, test_config, repo):
    node = make_discover(fake_bundle, repo, _LOG)
    result = node({"config": test_config})
    assert "step_log" in result
    assert result["step_log"][0].step == "discover_companies"
    assert result["step_log"][0].status == "ok"


# ---------------------------------------------------------------------------
# resolve_contacts
# ---------------------------------------------------------------------------

def test_resolve_drops_company_with_no_contact(fake_bundle, test_config):
    """Companies where contacts.resolve() returns None must be dropped."""
    from agent.providers.contacts.base import ContactResolutionProvider

    class NoContacts(ContactResolutionProvider):
        def resolve(self, company, target_titles):
            return None

    object.__setattr__(fake_bundle, "contacts", NoContacts())
    node = make_resolve(fake_bundle, _LOG)
    result = node({"config": test_config, "companies": SEED_COMPANIES})
    assert result["leads"] == []


def test_resolve_builds_leads(fake_bundle, test_config):
    node = make_resolve(fake_bundle, _LOG)
    result = node({"config": test_config, "companies": SEED_COMPANIES})
    leads = result["leads"]
    assert len(leads) == len(SEED_COMPANIES)
    assert all(isinstance(l, Lead) for l in leads)


# ---------------------------------------------------------------------------
# find_emails
# ---------------------------------------------------------------------------

def test_find_drops_lead_with_no_email(fake_bundle, test_config):
    from agent.providers.email_finder.base import EmailFinderProvider

    class NoEmail(EmailFinderProvider):
        def find(self, company, contact):
            return None

    object.__setattr__(fake_bundle, "email_finder", NoEmail())
    node = make_find(fake_bundle, _LOG)
    stub_leads = [
        Lead(company=SEED_COMPANIES[0], contact=SEED_CONTACT,
             email=VerifiedEmail("", "pending", False))
    ]
    result = node({"leads": stub_leads})
    assert result["leads"] == []


# ---------------------------------------------------------------------------
# verify_emails
# ---------------------------------------------------------------------------

def test_verify_drops_invalid(fake_bundle, test_config):
    """Leads with INVALID status must be removed."""
    from agent.providers.verifier.base import EmailVerifierProvider

    class AlwaysInvalid(EmailVerifierProvider):
        def verify(self, email):
            return VerificationStatus.INVALID

    object.__setattr__(fake_bundle, "verifier", AlwaysInvalid())
    node = make_verify(fake_bundle, test_config, _LOG)
    leads = [Lead(
        company=SEED_COMPANIES[0], contact=SEED_CONTACT,
        email=VerifiedEmail("x@y.com", "unverified", False)
    )]
    result = node({"leads": leads})
    assert result["leads"] == []


def test_verify_marks_catchall_risky(fake_bundle, test_config):
    """Catchall addresses must be kept but tagged risky=True."""
    from agent.providers.verifier.base import EmailVerifierProvider

    class CatchallVerifier(EmailVerifierProvider):
        def verify(self, email):
            return VerificationStatus.CATCHALL

    object.__setattr__(fake_bundle, "verifier", CatchallVerifier())
    node = make_verify(fake_bundle, test_config, _LOG)
    leads = [Lead(
        company=SEED_COMPANIES[0], contact=SEED_CONTACT,
        email=VerifiedEmail("x@y.com", "unverified", False)
    )]
    result = node({"leads": leads})
    assert len(result["leads"]) == 1
    assert result["leads"][0].email.risky is True


# ---------------------------------------------------------------------------
# generate_copy
# ---------------------------------------------------------------------------

def test_generate_copy_fills_fields(fake_bundle, test_config):
    node = make_copy(fake_bundle, test_config, _LOG)
    leads = [Lead(
        company=SEED_COMPANIES[0], contact=SEED_CONTACT,
        email=VerifiedEmail("alice@renewco.io", "valid", False)
    )]
    result = node({"leads": leads})
    lead = result["leads"][0]
    assert lead.pitch_email
    assert lead.follow_up
    assert lead.commonalities


def test_generate_copy_respects_max_leads(fake_bundle, test_config):
    """generate_copy must cap output to config.max_leads."""
    from dataclasses import replace
    config = replace(test_config, max_leads=1)
    node = make_copy(fake_bundle, config, _LOG)
    leads = [
        Lead(SEED_COMPANIES[0], SEED_CONTACT, VerifiedEmail("a@x.com", "valid", False)),
        Lead(SEED_COMPANIES[1], SEED_CONTACT, VerifiedEmail("b@x.com", "valid", False)),
    ]
    result = node({"leads": leads})
    assert len(result["leads"]) == 1


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

def test_route_after_discovery_empty():
    assert route_after_discovery({"companies": []}) == "end"


def test_route_after_discovery_non_empty():
    assert route_after_discovery({"companies": SEED_COMPANIES}) == "continue"


def test_route_after_verify_empty():
    assert route_after_verify({"leads": []}) == "end"


def test_route_after_verify_non_empty(sample_lead):
    assert route_after_verify({"leads": [sample_lead]}) == "continue"


# ---------------------------------------------------------------------------
# persist_rows / sync_drafts — only newly appended rows may be drafted
# ---------------------------------------------------------------------------

def test_persist_records_first_appended_row(repo, sample_lead):
    """The fixture workbook has a header (row 1) and one lead (row 2)."""
    node = make_persist(repo, _LOG)
    result = node({"leads": [sample_lead]})
    assert result["appended_row_count"] == 1
    assert result["drafts_start_row"] == 3


def test_persist_start_row_follows_existing_rows(repo, sample_lead):
    """A second append must start after the first one's rows."""
    node = make_persist(repo, _LOG)
    node({"leads": [sample_lead]})
    result = node({"leads": [sample_lead, sample_lead]})
    assert result["drafts_start_row"] == 4


def test_new_rows_only_are_readable_from_start_row(repo, tmp_xlsx, sample_lead):
    """The row range the persist node reports must select exactly the new rows."""
    from agent.tools.mailer.ingestion.xlsx_reader import read_campaign_rows

    result = make_persist(repo, _LOG)({"leads": [sample_lead]})
    rows = read_campaign_rows(str(tmp_xlsx), start_row=result["drafts_start_row"])
    assert [r.row_number for r in rows] == [3]
    assert rows[0].to_addr == "alice@renewco.io"


def test_sync_drafts_passes_start_row(test_config, monkeypatch):
    """Regression: sync_drafts used to draft every row because start_row was dropped."""
    from dataclasses import replace
    import agent.tools.drafts_tool as drafts_tool

    calls = []
    monkeypatch.setattr(
        drafts_tool, "run_drafts_sync",
        lambda **kwargs: calls.append(kwargs) or {"drafted": 1, "failed": 0},
    )
    config = replace(test_config, run_drafts_after=True)
    node = make_sync(config, _LOG)
    result = node({"appended_row_count": 1, "drafts_start_row": 3})

    assert calls == [{"xlsx_path": config.xlsx_path, "start_row": 3}]
    assert result["draft_result"]["drafted"] == 1


def test_sync_drafts_skips_when_nothing_appended(test_config, monkeypatch):
    from dataclasses import replace
    import agent.tools.drafts_tool as drafts_tool

    def fail(**kwargs):
        raise AssertionError("must not draft when no rows were appended")

    monkeypatch.setattr(drafts_tool, "run_drafts_sync", fail)
    node = make_sync(replace(test_config, run_drafts_after=True), _LOG)
    result = node({"appended_row_count": 0})
    assert result["draft_result"]["skipped"] is True


def test_sync_drafts_refuses_to_draft_without_start_row(test_config, monkeypatch):
    """Without a start row the tool would draft the whole workbook, so it must refuse."""
    from dataclasses import replace
    import agent.tools.drafts_tool as drafts_tool

    def fail(**kwargs):
        raise AssertionError("must not draft without a start row")

    monkeypatch.setattr(drafts_tool, "run_drafts_sync", fail)
    node = make_sync(replace(test_config, run_drafts_after=True), _LOG)
    result = node({"appended_row_count": 1})
    assert "drafts_start_row" in result["errors"][0]
