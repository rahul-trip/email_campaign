"""Vendor API keys the platform pays for (Phase 6d.4): encrypted, versioned, never listed in full.

A platform table, reached only through the platform unit of work. Replacing a key retires the
current version instead of overwriting it; a retired version can be restored for 30 days."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from outbound.db.crypto import Keyring, Sealed
from outbound.db.models import PlatformCredentialRow
from outbound.db.types import utcnow
from outbound.domain.errors import InvalidInput
from outbound.domain.vendors import RETIRED_KEPT_DAYS


@dataclass(frozen=True)
class KeySummary:
    """What the console may show about a key: never the key."""

    vendor: str
    version: int
    last4: str
    set_at: datetime
    set_by: str | None
    can_roll_back: bool


def _aad(vendor: str, version: int) -> bytes:
    return f"platform|{vendor}|{version}".encode()


class VendorKeyRepository:
    def __init__(self, session: Session, keyring: Keyring) -> None:
        self._session = session
        self._keyring = keyring

    def _active(self) -> list[PlatformCredentialRow]:
        stmt = select(PlatformCredentialRow).where(PlatformCredentialRow.active.is_(True))
        return list(self._session.scalars(stmt))

    def stamp(self) -> tuple[tuple[str, int], ...]:
        """Which version of each key is live; cheap, so it is checked before every run."""
        return tuple(sorted((r.vendor, r.version) for r in self._active()))

    def current(self) -> dict[str, str]:
        """Every live key in clear, by vendor. For building adapters only."""
        return {r.vendor: self._open(r) for r in self._active()}

    def summaries(self) -> dict[str, KeySummary]:
        cutoff = utcnow() - timedelta(days=RETIRED_KEPT_DAYS)
        out: dict[str, KeySummary] = {}
        for row in self._active():
            previous = self._session.scalar(
                select(func.count())
                .select_from(PlatformCredentialRow)
                .where(
                    PlatformCredentialRow.vendor == row.vendor,
                    PlatformCredentialRow.active.is_(False),
                    PlatformCredentialRow.retired_at >= cutoff,
                )
            )
            out[row.vendor] = KeySummary(
                row.vendor, row.version, row.last4, row.created_at, row.created_by, bool(previous)
            )
        return out

    def put(self, vendor: str, key: str, *, by: str | None) -> int:
        """Make ``key`` the live key of ``vendor``; the old one is retired, not deleted."""
        now = utcnow()
        latest = self._session.scalar(
            select(func.max(PlatformCredentialRow.version)).where(
                PlatformCredentialRow.vendor == vendor
            )
        )
        for row in self._active():
            if row.vendor == vendor:
                row.active, row.retired_at = False, now
        version = (latest or 0) + 1
        sealed = self._keyring.seal(key, _aad(vendor, version))
        self._session.add(
            PlatformCredentialRow(
                vendor=vendor,
                version=version,
                key_version=sealed.key_version,
                nonce=sealed.nonce,
                ciphertext=sealed.ciphertext,
                last4=key[-4:],
                active=True,
                created_by=by,
                created_at=now,
            )
        )
        self._session.execute(
            delete(PlatformCredentialRow).where(
                PlatformCredentialRow.active.is_(False),
                PlatformCredentialRow.retired_at < now - timedelta(days=RETIRED_KEPT_DAYS),
            )
        )
        self._session.flush()
        return version

    def roll_back(self, vendor: str) -> int:
        """Make the most recently retired key live again, retiring the current one."""
        cutoff = utcnow() - timedelta(days=RETIRED_KEPT_DAYS)
        previous = self._session.scalars(
            select(PlatformCredentialRow)
            .where(
                PlatformCredentialRow.vendor == vendor,
                PlatformCredentialRow.active.is_(False),
                PlatformCredentialRow.retired_at >= cutoff,
            )
            .order_by(PlatformCredentialRow.version.desc())
        ).first()
        if previous is None:
            raise InvalidInput(f"no earlier key of {vendor} to go back to")
        for row in self._active():
            if row.vendor == vendor:
                row.active, row.retired_at = False, utcnow()
        previous.active, previous.retired_at = True, None
        self._session.flush()
        return previous.version

    def reveal(self, vendor: str) -> str:
        for row in self._active():
            if row.vendor == vendor:
                return self._open(row)
        raise InvalidInput(f"{vendor} has no key")

    def _open(self, row: PlatformCredentialRow) -> str:
        sealed = Sealed(row.key_version, row.nonce, row.ciphertext)
        return self._keyring.open(sealed, _aad(row.vendor, row.version))

    def reseal_all(self) -> int:
        """Seal every key (retired ones too) again with the newest key; for `secrets rotate`."""
        rows = list(self._session.scalars(select(PlatformCredentialRow)))
        for row in rows:
            sealed = self._keyring.seal(self._open(row), _aad(row.vendor, row.version))
            row.key_version, row.nonce, row.ciphertext = (
                sealed.key_version,
                sealed.nonce,
                sealed.ciphertext,
            )
        self._session.flush()
        return len(rows)
