"""agent/providers/contacts/brightdata.py — Bright Data LinkedIn Scraper adapter.

Adapter pattern: wraps Bright Data's Dataset API (used to trigger their
LinkedIn People Search scraper, poll for completion, and fetch results) and
maps the response into our Contact domain object.

Unlike Proxycurl's synchronous request/response, Bright Data's Dataset API is
async: trigger a "snapshot" job, poll until it's ready, then fetch results.

API docs: https://docs.brightdata.com/api-reference/marketplace-dataset-api

NOTE: Bright Data offers several distinct LinkedIn datasets (People Search,
People Profile, Company, ...), each with its own expected input/output
schema. This adapter targets the LinkedIn People Search collector's common
shape (search by a LinkedIn people-search URL, get back a list of profiles).
Confirm field names below against the exact dataset attached to your
BRIGHTDATA_LINKEDIN_DATASET_ID and adjust `_build_contact` if your dataset's
output fields differ.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.domain.models import Company, Contact
from agent.providers.discovery.base import ProviderError
from .base import ContactResolutionProvider

logger = logging.getLogger(__name__)

_TRIGGER_URL = "https://api.brightdata.com/datasets/v3/trigger"
_PROGRESS_URL = "https://api.brightdata.com/datasets/v3/progress/{snapshot_id}"
_SNAPSHOT_URL = "https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}"


class BrightDataContactProvider(ContactResolutionProvider):
    """Resolves the best POC at a company using Bright Data's LinkedIn scraper.

    Strategy:
        - For each target title (priority order), trigger a LinkedIn people-
          search snapshot job for "<title> at <company>".
        - Poll until the snapshot is ready (bounded by max_poll_attempts).
        - Return the first profile found; if none for any title, return None.
    """

    def __init__(
        self,
        api_key: str,
        dataset_id: str,
        per_call_delay_seconds: float = 1.0,
        poll_interval_seconds: float = 3.0,
        max_poll_attempts: int = 40,
    ) -> None:
        if not api_key:
            raise ProviderError("BRIGHTDATA_API_KEY is not set.")
        if not dataset_id:
            raise ProviderError("BRIGHTDATA_LINKEDIN_DATASET_ID is not set.")
        self._api_key = api_key
        self._dataset_id = dataset_id
        self._delay = per_call_delay_seconds
        self._poll_interval = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def resolve(self, company: Company, target_titles: list[str]) -> Contact | None:
        logger.debug("BrightData.resolve company=%s", company.domain)

        for title in target_titles:
            profiles = self._search_people(company, title)
            if profiles:
                return self._build_contact(profiles[0])
            if self._delay:
                time.sleep(self._delay)

        logger.debug("BrightData: no contact found for %s", company.domain)
        return None

    def _search_people(self, company: Company, title: str) -> list[dict]:
        search_url = (
            "https://www.linkedin.com/search/results/people/"
            f"?keywords={quote(title)}%20{quote(company.name)}"
        )
        snapshot_id = self._trigger_snapshot(search_url)
        if not snapshot_id:
            return []
        return self._poll_and_fetch(snapshot_id)

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _trigger_snapshot(self, search_url: str) -> str | None:
        params = {"dataset_id": self._dataset_id, "include_errors": "true"}
        body = [{"url": search_url}]
        try:
            resp = requests.post(_TRIGGER_URL, headers=self._headers,
                                  params=params, json=body, timeout=20)
        except requests.exceptions.RequestException as exc:
            logger.warning("BrightData trigger error: %s", exc)
            raise

        if resp.status_code in (429, 503):
            raise requests.exceptions.ConnectionError(f"BrightData rate-limited: {resp.status_code}")

        if not resp.ok:
            logger.warning("BrightData trigger HTTP %d: %s", resp.status_code, resp.text[:200])
            return None

        data = resp.json()
        snapshot_id = data.get("snapshot_id")
        if not snapshot_id:
            logger.warning("BrightData trigger response missing snapshot_id: %s", data)
        return snapshot_id

    def _poll_and_fetch(self, snapshot_id: str) -> list[dict]:
        for attempt in range(self._max_poll_attempts):
            status = self._check_progress(snapshot_id)
            if status == "ready":
                return self._fetch_snapshot(snapshot_id)
            if status in ("failed", "canceled"):
                logger.warning("BrightData snapshot %s ended with status=%s", snapshot_id, status)
                return []
            time.sleep(self._poll_interval)

        logger.warning("BrightData snapshot %s did not complete after %d attempts",
                        snapshot_id, self._max_poll_attempts)
        return []

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _check_progress(self, snapshot_id: str) -> str:
        try:
            resp = requests.get(_PROGRESS_URL.format(snapshot_id=snapshot_id),
                                 headers=self._headers, timeout=15)
        except requests.exceptions.RequestException as exc:
            logger.warning("BrightData progress error: %s", exc)
            raise

        if resp.status_code in (429, 503):
            raise requests.exceptions.ConnectionError(f"BrightData rate-limited: {resp.status_code}")

        if not resp.ok:
            logger.warning("BrightData progress HTTP %d: %s", resp.status_code, resp.text[:200])
            return "failed"

        return resp.json().get("status", "running")

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _fetch_snapshot(self, snapshot_id: str) -> list[dict]:
        try:
            resp = requests.get(_SNAPSHOT_URL.format(snapshot_id=snapshot_id),
                                 headers=self._headers, params={"format": "json"}, timeout=30)
        except requests.exceptions.RequestException as exc:
            logger.warning("BrightData snapshot fetch error: %s", exc)
            raise

        if resp.status_code in (429, 503):
            raise requests.exceptions.ConnectionError(f"BrightData rate-limited: {resp.status_code}")

        if not resp.ok:
            logger.warning("BrightData snapshot HTTP %d: %s", resp.status_code, resp.text[:200])
            return []

        data = resp.json()
        return data if isinstance(data, list) else data.get("results", [])

    def _build_contact(self, profile: dict) -> Contact:
        full_name = profile.get("name") or profile.get("full_name") or "Unknown"
        title = profile.get("position") or profile.get("title") or profile.get("headline") or "Unknown"
        linkedin_url = profile.get("url") or profile.get("profile_url") or ""
        about = profile.get("about") or profile.get("summary") or ""
        eccentricities = about[:250]

        return Contact(
            full_name=full_name,
            title=title,
            linkedin_url=linkedin_url,
            eccentricities=eccentricities,
        )
