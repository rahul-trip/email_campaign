"""agent/providers/verifier/base.py — Strategy ABC for email verification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class VerificationStatus(str, Enum):
    """Normalized email-verification outcomes (vendor-agnostic)."""

    VALID = "valid"
    CATCHALL = "catchall"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class EmailVerifierProvider(ABC):
    """Strategy interface for email address verification.

    Implementations:
        neverbounce.NeverBounceVerifier — NeverBounce single-check API
    """

    @abstractmethod
    def verify(self, email: str) -> VerificationStatus:
        """Return the normalized verification status for *email*.

        Args:
            email: The email address to verify.

        Returns:
            A VerificationStatus enum value.
        """
        ...
