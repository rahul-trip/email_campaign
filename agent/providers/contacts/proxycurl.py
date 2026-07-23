"""agent/providers/contacts/proxycurl.py — Proxycurl contact-resolution adapter.

Adapter pattern: wraps Proxycurl's LinkedIn-based company/person APIs and maps
their JSON response into our Contact domain object.

API docs: https://nubela.co/proxycurl/docs
"""

from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.domain.models import Company, Contact
from agent.providers.discovery.base import ProviderError
from .base import ContactResolutionProvider

logger = logging.getLogger(__name__)

_COMPANY_SEARCH_URL = "https://nubela.co/proxycurl/api/linkedin/company/employees/"
_PERSON_URL = "https://nubela.co/proxycurl/api/v2/linkedin"


class ProxycurlContactProvider(ContactResolutionProvider):
    """Resolves the best POC at a company using Proxycurl's LinkedIn search.

    Strategy:
        - Search for employees by each target title (priority order).
        - Return the first match; if none, return None (node skips company).
        - Pulls bio/headline into eccentricities for the "POC Details" column.
    """

    def __init__(self, api_key: str, per_call_delay_seconds: float = 1.0) -> None:
        if not api_key:
            raise ProviderError("PROXYCURL_API_KEY is not set.")
        self._api_key = api_key
        self._delay = per_call_delay_seconds
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def resolve(self, company: Company, target_titles: list[str]) -> Contact | None:
        logger.debug("Proxycurl.resolve company=%s", company.domain)

        for title in target_titles:
            employees = self._search_employees(company.domain, title)
            if employees:
                person = employees[0]
                return self._build_contact(person)
            if self._delay:
                time.sleep(self._delay)

        logger.debug("Proxycurl: no contact found for %s", company.domain)
        return None

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _search_employees(self, domain: str, title: str) -> list[dict]:
        params = {
            "company_domain": domain,
            "role": title,
            "enrich_profiles": "skip",
            "page_size": 1,
        }
        try:
            resp = requests.get(_COMPANY_SEARCH_URL, headers=self._headers,
                                params=params, timeout=20)
        except requests.exceptions.RequestException as exc:
            logger.warning("Proxycurl search error (domain=%s): %s", domain, exc)
            raise

        if resp.status_code in (429, 503):
            raise requests.exceptions.ConnectionError(f"Proxycurl rate-limited: {resp.status_code}")

        if not resp.ok:
            logger.warning("Proxycurl search HTTP %d for %s/%s", resp.status_code, domain, title)
            return []

        data = resp.json()
        return data.get("employees", [])

    def _build_contact(self, employee: dict) -> Contact:
        profile = employee.get("profile") or {}
        full_name = (profile.get("full_name") or
                     f"{profile.get('first_name', '')} {profile.get('last_name', '')}").strip()
        title = profile.get("occupation") or profile.get("headline") or "Unknown"
        linkedin_url = employee.get("profile_url") or profile.get("public_identifier", "")
        headline = profile.get("headline") or ""
        summary = profile.get("summary") or ""
        eccentricities = (headline + (". " + summary[:200] if summary else "")).strip()

        return Contact(
            full_name=full_name or "Unknown",
            title=title,
            linkedin_url=linkedin_url,
            eccentricities=eccentricities,
        )
