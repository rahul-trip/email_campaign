"""agent/providers/email_finder/base.py — Strategy ABC for email finding."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent.domain.models import Company, Contact


class EmailFinderProvider(ABC):
    """Strategy interface for finding a person's business email.

    Implementations:
        hunter.HunterEmailFinder — Hunter.io Email Finder API
    """

    @abstractmethod
    def find(self, company: Company, contact: Contact) -> str | None:
        """Return the business email address, or None if not found.

        Args:
            company: The target company (domain used for lookup).
            contact: The resolved POC (first/last name used for lookup).

        Returns:
            Email string or None.
        """
        ...
