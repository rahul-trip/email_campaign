"""agent/graph/nodes.py — One function per pipeline stage + router functions.

Design principles:
    - Command / single-responsibility: each node does one thing.
    - Dependency Injection: providers, repo, config, logger are injected via
      make_* closures; nodes never construct providers themselves (testable).
    - All nodes are wrapped with @logged_step from observability/step_logger.py.

Node signatures all follow the LangGraph contract:
    def node(state: AgentState) -> dict   # returns only the keys it updates

Router functions return a string key that LangGraph uses for conditional edges:
    "continue" → next node  |  "end" → END
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable

from agent.config.models import AgentConfig
from agent.domain.models import Company, Lead, VerifiedEmail
from agent.graph.state import AgentState
from agent.observability.step_logger import logged_step
from agent.persistence.lead_repository import XlsxLeadRepository
from agent.providers.bundle import ProviderBundle
from agent.providers.verifier.base import VerificationStatus

logger = logging.getLogger("agent")


# ---------------------------------------------------------------------------
# Node factories (closures for dependency injection)
# ---------------------------------------------------------------------------

def make_discover(
    bundle: ProviderBundle,
    repo: XlsxLeadRepository,
    log: logging.Logger,
) -> Callable[[AgentState], dict]:
    """Stage 1 — Discover companies via the discovery provider."""

    @logged_step("discover_companies")
    def discover_companies(state: AgentState) -> dict:
        config: AgentConfig = state["config"]
        existing = repo.existing_domains()

        raw_companies = bundle.discovery.discover(
            keywords=config.keywords,
            location=config.location,
            limit=config.max_companies * 3,  # over-fetch to account for deduplication
        )

        # Filter out domains already in the workbook
        companies: list[Company] = []
        for c in raw_companies:
            if c.domain in existing:
                log.debug("discover: skipping known domain %s", c.domain)
            else:
                companies.append(c)
            if len(companies) >= config.max_companies:
                break

        log.info("discover_companies: %d new companies (filtered from %d raw, %d known)",
                 len(companies), len(raw_companies), len(existing))
        return {"companies": companies}

    return discover_companies


def make_resolve(
    bundle: ProviderBundle,
    log: logging.Logger,
) -> Callable[[AgentState], dict]:
    """Stage 2 — Resolve best POC contact for each company."""

    @logged_step("resolve_contacts")
    def resolve_contacts(state: AgentState) -> dict:
        config: AgentConfig = state["config"]
        companies: list[Company] = state.get("companies", [])

        leads: list[Lead] = []
        for company in companies:
            contact = bundle.contacts.resolve(company, config.target_titles)
            if contact is None:
                log.debug("resolve_contacts: no contact found for %s — skipping", company.name)
                continue
            leads.append(Lead(
                company=company,
                contact=contact,
                email=VerifiedEmail(address="", status="pending", risky=False),
            ))

        log.info("resolve_contacts: %d/%d companies have a contact", len(leads), len(companies))
        return {"leads": leads}

    return resolve_contacts


def make_find(
    bundle: ProviderBundle,
    log: logging.Logger,
) -> Callable[[AgentState], dict]:
    """Stage 3 — Find the business email for each lead."""

    @logged_step("find_emails")
    def find_emails(state: AgentState) -> dict:
        leads: list[Lead] = state.get("leads", [])
        enriched: list[Lead] = []

        for lead in leads:
            email_str = bundle.email_finder.find(lead.company, lead.contact)
            if not email_str:
                log.debug("find_emails: no email for %s @ %s — dropping",
                          lead.contact.full_name, lead.company.name)
                continue
            enriched.append(replace(lead, email=VerifiedEmail(
                address=email_str, status="unverified", risky=False
            )))

        log.info("find_emails: %d/%d leads have an email", len(enriched), len(leads))
        return {"leads": enriched}

    return find_emails


def make_verify(
    bundle: ProviderBundle,
    config: AgentConfig,
    log: logging.Logger,
) -> Callable[[AgentState], dict]:
    """Stage 4 — Verify emails and apply keep/risk policy from config."""

    @logged_step("verify_emails")
    def verify_emails(state: AgentState) -> dict:
        leads: list[Lead] = state.get("leads", [])
        kept: list[Lead] = []

        for lead in leads:
            status = bundle.verifier.verify(lead.email.address)
            risky = status.value in config.mark_risky_statuses

            if status == VerificationStatus.INVALID or status.value not in config.keep_statuses:
                log.debug("verify_emails: dropping %s (status=%s)", lead.email.address, status)
                continue

            kept.append(replace(lead, email=replace(
                lead.email, status=status.value, risky=risky
            )))
            log.debug("verify_emails: kept %s (status=%s risky=%s)",
                      lead.email.address, status, risky)

        log.info("verify_emails: %d/%d leads passed verification", len(kept), len(leads))
        return {"leads": kept}

    return verify_emails


def make_copy(
    bundle: ProviderBundle,
    config: AgentConfig,
    log: logging.Logger,
) -> Callable[[AgentState], dict]:
    """Stage 5 — Generate pitch_email, follow_up, and commonalities."""

    @logged_step("generate_copy")
    def generate_copy(state: AgentState) -> dict:
        leads: list[Lead] = state.get("leads", [])
        # Apply max_leads cap before generating copy (saves API credits for LLM adapters)
        leads = leads[: config.max_leads]

        with_copy: list[Lead] = []
        for lead in leads:
            copy_out = bundle.copywriter.write(lead.company, lead.contact, config)
            with_copy.append(replace(lead,
                pitch_email=copy_out.pitch_email,
                follow_up=copy_out.follow_up,
                commonalities=copy_out.commonalities,
            ))

        log.info("generate_copy: generated copy for %d leads", len(with_copy))
        return {"leads": with_copy}

    return generate_copy


def make_persist(
    repo: XlsxLeadRepository,
    log: logging.Logger,
) -> Callable[[AgentState], dict]:
    """Stage 6 — Append leads to the xlsx workbook."""

    @logged_step("persist_rows")
    def persist_rows(state: AgentState) -> dict:
        leads: list[Lead] = state.get("leads", [])
        count = repo.append_leads(leads)
        log.info("persist_rows: appended %d rows", count)
        return {"appended_row_count": count}

    return persist_rows


def make_sync(
    config: AgentConfig,
    log: logging.Logger,
) -> Callable[[AgentState], dict]:
    """Stage 7 — Invoke the mailer tool's Campaign-to-Drafts sync for new rows."""

    @logged_step("sync_drafts")
    def sync_drafts(state: AgentState) -> dict:
        if not config.run_drafts_after:
            log.info("sync_drafts: skipped (run_drafts_after=false)")
            return {"draft_result": {"skipped": True}}

        appended = state.get("appended_row_count", 0)
        if appended == 0:
            log.info("sync_drafts: no rows appended — nothing to draft")
            return {"draft_result": {"skipped": True, "reason": "no rows appended"}}

        # The pre-append row_count is not stored in state, so we derive it:
        # total current rows minus what we just appended.
        # Import inline to avoid circular deps and because this is a tool boundary.
        from agent.tools.drafts_tool import run_drafts_sync
        result = run_drafts_sync(xlsx_path=config.xlsx_path)
        log.info("sync_drafts: drafted=%s failed=%s",
                 result.get("drafted"), result.get("failed"))
        return {"draft_result": result}

    return sync_drafts


# ---------------------------------------------------------------------------
# Router functions (pure, no side effects)
# ---------------------------------------------------------------------------

def route_after_discovery(state: AgentState) -> str:
    """Route to 'resolve_contacts' if companies were found, else 'end'."""
    companies = state.get("companies", [])
    if not companies:
        logger.info("router: no companies discovered — ending run")
        return "end"
    return "continue"


def route_after_verify(state: AgentState) -> str:
    """Route to 'generate_copy' if any leads survived verification, else 'end'."""
    leads = state.get("leads", [])
    if not leads:
        logger.info("router: no leads survived verification — ending run")
        return "end"
    return "continue"
