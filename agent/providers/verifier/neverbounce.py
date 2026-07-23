"""agent/providers/verifier/neverbounce.py — NeverBounce email-verification adapter.

Adapter pattern: wraps NeverBounce's single-check API and maps their result
codes into our VerificationStatus enum.

API docs: https://developers.neverbounce.com/reference/single-check
"""

from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.providers.discovery.base import ProviderError
from .base import EmailVerifierProvider, VerificationStatus

logger = logging.getLogger(__name__)

_CHECK_URL = "https://api.neverbounce.com/v4/single/check"

# Map NeverBounce result strings → our normalized VerificationStatus.
# NeverBounce can return: valid, invalid, catchall, unknown, disposable, accept_all
_STATUS_MAP: dict[str, VerificationStatus] = {
    "valid":       VerificationStatus.VALID,
    "catchall":    VerificationStatus.CATCHALL,
    "accept_all":  VerificationStatus.CATCHALL,  # equivalent bucket
    "unknown":     VerificationStatus.UNKNOWN,
    "disposable":  VerificationStatus.INVALID,   # treat as invalid
    "invalid":     VerificationStatus.INVALID,
}


class NeverBounceVerifier(EmailVerifierProvider):
    """Verifies email addresses via NeverBounce's single-check endpoint."""

    def __init__(self, api_key: str, per_call_delay_seconds: float = 1.0) -> None:
        if not api_key:
            raise ProviderError("NEVERBOUNCE_API_KEY is not set.")
        self._api_key = api_key
        self._delay = per_call_delay_seconds

    def verify(self, email: str) -> VerificationStatus:
        logger.debug("NeverBounce.verify email=%s", email)
        status = self._call_api(email)
        if self._delay:
            time.sleep(self._delay)
        return status

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_api(self, email: str) -> VerificationStatus:
        params = {
            "key": self._api_key,
            "email": email,
            "address_info": 0,
            "credits_info": 0,
        }
        try:
            resp = requests.get(_CHECK_URL, params=params, timeout=15)
        except requests.exceptions.RequestException as exc:
            logger.warning("NeverBounce request error: %s", exc)
            raise

        if resp.status_code == 429:
            raise requests.exceptions.ConnectionError("NeverBounce rate-limited (429)")

        if resp.status_code >= 500:
            raise requests.exceptions.ConnectionError(f"NeverBounce server error {resp.status_code}")

        if not resp.ok:
            logger.warning("NeverBounce HTTP %d: %s", resp.status_code, resp.text[:200])
            # Default to unknown on unexpected errors to avoid silently dropping
            return VerificationStatus.UNKNOWN

        data = resp.json()
        raw_result = data.get("result", "unknown")
        status = _STATUS_MAP.get(raw_result, VerificationStatus.UNKNOWN)
        logger.debug("NeverBounce result for %s: raw=%r → %s", email, raw_result, status)
        return status
