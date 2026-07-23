"""agent/providers/email_finder/hunter.py — Hunter.io Email Finder adapter.

Adapter pattern: wraps Hunter.io's Email Finder API and returns a plain string
(or None). The domain object is never exposed to the rest of the codebase.

API docs: https://hunter.io/api-documentation/v2#email-finder
"""

from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.domain.models import Company, Contact
from agent.providers.discovery.base import ProviderError
from .base import EmailFinderProvider

logger = logging.getLogger(__name__)

_FINDER_URL = "https://api.hunter.io/v2/email-finder"


class HunterEmailFinder(EmailFinderProvider):
    """Finds a business email via Hunter.io's Email Finder endpoint.

    Uses the company domain + contact first/last name for lookup.
    """

    def __init__(self, api_key: str, per_call_delay_seconds: float = 1.0) -> None:
        if not api_key:
            raise ProviderError("HUNTER_API_KEY is not set.")
        self._api_key = api_key
        self._delay = per_call_delay_seconds

    def find(self, company: Company, contact: Contact) -> str | None:
        parts = contact.full_name.strip().split()
        first_name = parts[0] if parts else ""
        last_name = parts[-1] if len(parts) > 1 else ""

        logger.debug("Hunter.find domain=%s name=%s %s", company.domain, first_name, last_name)

        result = self._call_api(company.domain, first_name, last_name)
        if self._delay:
            time.sleep(self._delay)
        return result

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_api(self, domain: str, first_name: str, last_name: str) -> str | None:
        params = {
            "domain": domain,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": self._api_key,
        }
        try:
            resp = requests.get(_FINDER_URL, params=params, timeout=15)
        except requests.exceptions.RequestException as exc:
            logger.warning("Hunter.io request error: %s", exc)
            raise

        if resp.status_code == 429:
            raise requests.exceptions.ConnectionError("Hunter.io rate-limited (429)")

        if resp.status_code >= 500:
            raise requests.exceptions.ConnectionError(f"Hunter.io server error {resp.status_code}")

        if not resp.ok:
            logger.warning("Hunter.io HTTP %d: %s", resp.status_code, resp.text[:200])
            return None

        data = resp.json()
        email = (data.get("data") or {}).get("email")
        if email:
            logger.debug("Hunter.io found email: %s", email)
        else:
            logger.debug("Hunter.io: no email found for %s@%s", first_name, domain)
        return email or None
