"""agent/providers/contacts/base.py — Strategy ABC for contact resolution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent.domain.models import Company, Contact


class ContactResolutionProvider(ABC):
    """Strategy interface for resolving the best POC at a company.

    Implementations:
        brightdata.BrightDataContactProvider — Bright Data LinkedIn Scraper API (default)
        proxycurl.ProxycurlContactProvider — Proxycurl LinkedIn API
    """

    @abstractmethod
    def resolve(self, company: Company, target_titles: list[str]) -> Contact | None:
        """Find the highest-priority person matching *target_titles*.

        Args:
            company:       The target company.
            target_titles: Job titles in descending priority order.

        Returns:
            A Contact, or None if nobody matching is found.
        """
        ...
