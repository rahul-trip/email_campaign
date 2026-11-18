"""ZeroBounce: email finder (guessformat) and email validator.

Docs: https://www.zerobounce.net/docs/email-finder-api and
https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-validate-emails

ZeroBounce reports a bad key or no credits as a JSON ``error`` body, sometimes with HTTP 200,
so that is checked as well as the status code. A finder lookup that finds nothing costs no
credit, and neither does an ``unknown`` validation.
"""

from __future__ import annotations

from typing import Any

import httpx

from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import (
    FinderResult,
    PersonQuery,
    VerificationResult,
    VerificationStatus,
)

BASE_URL = "https://api.zerobounce.net/v2"

# Our own numeric scale for ZeroBounce's HIGH / MEDIUM / LOW email_confidence labels.
_CONFIDENCE = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}

# Anything ZeroBounce flags as abusive, a trap or "do not mail" is never safe to send to.
_VERIFY_MAP = {
    "valid": VerificationStatus.VALID,
    "catch-all": VerificationStatus.CATCH_ALL,
    "invalid": VerificationStatus.INVALID,
    "spamtrap": VerificationStatus.INVALID,
    "abuse": VerificationStatus.INVALID,
    "do_not_mail": VerificationStatus.INVALID,
    "unknown": VerificationStatus.UNKNOWN,
}


def _check_error(provider: str, payload: dict[str, Any]) -> None:
    """ZeroBounce reports trouble in an ``error`` field, or, for a bad key or an empty account,
    in a ``Message`` field with HTTP 200 (read as "nothing found" until 2026-11-18)."""
    error = payload.get("error") or payload.get("Error")
    if error:
        text = str(error)
        if "key" in text.lower() or "credit" in text.lower():
            raise ProviderAuthError(provider, text)
        raise ProviderError(provider, text)
    message = payload.get("Message")
    if isinstance(message, str) and ("key" in message.lower() or "credit" in message.lower()):
        raise _KeyOrCredit(provider, message)


class _KeyOrCredit(ProviderAuthError):
    """ZeroBounce uses one sentence for a bad key and for no credits ("Invalid API key or your
    account ran out of credits"); ``_ZeroBounceBase._get`` settles which with a free call."""


class _ZeroBounceBase:
    name = "zerobounce"

    def __init__(
        self, api_key: str, *, client: httpx.Client | None = None, base_url: str = BASE_URL
    ) -> None:
        self._api_key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, base_url, client=client)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = self._http.get_object(path, {**params, "api_key": self._api_key})
        if not isinstance(payload, dict):
            raise ProviderError(self.name, f"GET {path}: unexpected response shape")
        try:
            _check_error(self.name, payload)
        except _KeyOrCredit as unclear:
            raise self._key_or_credit(str(unclear)) from None
        return payload

    def _key_or_credit(self, message: str) -> ProviderError:
        """``getcredits`` is free: it answers -1 for a key it does not know, else the balance."""
        try:
            credits = self._http.get_object("/getcredits", {"api_key": self._api_key}).get(
                "Credits"
            )
        except ProviderError:
            return ProviderAuthError(self.name, message)
        if str(credits).strip() == "-1":
            return ProviderAuthError(self.name, "the API key is not valid")
        return BudgetExceeded(self.name, "the account is out of credits")


class ZeroBounceFinder(_ZeroBounceBase):
    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        payload = self._get(
            "/guessformat",
            {
                "domain": domain,
                "first_name": person.first_name,
                "last_name": person.last_name,
            },
        )
        email = (payload.get("email") or "").strip().lower() or None
        label = str(payload.get("email_confidence") or "").upper()
        return FinderResult(
            email=email,
            provider=self.name,
            confidence=_CONFIDENCE.get(label) if email else None,
            raw_status=label or str(payload.get("failure_reason") or ""),
            billed=email is not None,
        )


class ZeroBounceVerifier(_ZeroBounceBase):
    def verify(self, email: str) -> VerificationResult:
        payload = self._get("/validate", {"email": email})
        raw = str(payload.get("status") or "unknown").lower()
        status = _VERIFY_MAP.get(raw, VerificationStatus.UNKNOWN)
        return VerificationResult(
            email=email,
            status=status,
            provider=self.name,
            raw_status=raw,
            billed=status is not VerificationStatus.UNKNOWN,
        )
