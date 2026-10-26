"""Rules of the verified lead directory (Phase 6g). No I/O.

The directory holds verified business facts shared between customers. What may be served, what
is worth contributing, and how a person is named for matching are decided here; storing them is
``outbound.db.repositories.directory``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from outbound.domain.enums import DirectoryStatus, EmailStatus

DIRECTORY = "directory"  # its provider name in the cost ledger, and its finder's name

# Facts not confirmed again within this window are deleted.
RETENTION = timedelta(days=730)
# Only an address a verifier proved is worth sharing.
CONTRIBUTABLE = (EmailStatus.VALID, EmailStatus.CATCH_ALL_RESOLVED)


def person_key(first_name: str, last_name: str) -> tuple[str, str]:
    """How two customers' spellings of one person meet: trimmed and lower case."""
    return " ".join(first_name.lower().split()), " ".join(last_name.lower().split())


def servable(status: DirectoryStatus, verified_at: datetime, now: datetime) -> bool:
    """Only an undisputed, not-yet-expired fact is served. Every served address is verified once
    more before it is used (the waterfall always does), so how old it is matters little."""
    return status is DirectoryStatus.VERIFIED and now - verified_at <= RETENTION


def month(when: datetime) -> str:
    """The only date a customer sees: the month, so a hit never shows when someone else looked."""
    return f"{when:%Y-%m}"


@dataclass(frozen=True)
class DirectoryHit:
    """A served address, with nothing about who contributed it or when it was looked up."""

    email: str
    source: str
    verified_month: str
