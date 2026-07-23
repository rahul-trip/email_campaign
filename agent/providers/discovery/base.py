"""agent/providers/discovery/base.py — Strategy ABC for company discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent.domain.models import Company


class CompanyDiscoveryProvider(ABC):
    """Strategy interface for discovering target companies.

    Implementations:
        google_cse.GoogleCseDiscoveryProvider — Google Custom Search JSON API
    """

    @abstractmethod
    def discover(self, keywords: list[str], location: str, limit: int) -> list[Company]:
        """Return up to *limit* Company objects matching the given keywords + location.

        Args:
            keywords: The search keyword phrases.
            location: Region/country string to append to the query.
            limit:    Maximum number of companies to return.

        Returns:
            A deduplicated list of Company objects (by domain).
        """
        ...


class ProviderError(RuntimeError):
    """Raised by any provider adapter on an unrecoverable error."""
