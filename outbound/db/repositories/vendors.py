"""Vendor API keys the platform pays for (Phase 6d.4): encrypted, versioned, never listed in full.

A platform table, reached only through the platform unit of work. Replacing a key retires the
current version instead of overwriting it; a retired version can be restored for 30 days. A
vendor has any number of live keys, one per slot; each slot is replaced, rolled back and removed
on its own."""

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
    slot: int
    version: int
    last4: str
    set_at: datetime
    set_by: str | None
    can_roll_back: bool


def _check_slot(slot: int) -> None:
    if slot < 1:
        raise InvalidInput("key slots start at 1")


def _aad(vendor: str, version: int) -> bytes:
    return f"platform|{vendor}|{version}".encode()


class VendorKeyRepository:
    def __init__(self, session: Session, keyring: Keyring) -> None:
        self._session = session
        self._keyring = keyring

    def _active(self) -> list[PlatformCredentialRow]:
        stmt = (
            select(PlatformCredentialRow)
            .where(PlatformCredentialRow.active.is_(True))
            .order_by(PlatformCredentialRow.vendor, PlatformCredentialRow.slot)
        )
        return list(self._session.scalars(stmt))

    def stamp(self) -> tuple[tuple[str, int], ...]:
        """Which version of each key is live; cheap, so it is checked before every run."""
        return tuple(sorted((f"{r.vendor}:{r.slot}", r.version) for r in self._active()))

    def current(self) -> dict[str, list[str]]:
        """Every live key in clear, by vendor, in slot order. For building adapters only."""
        out: dict[str, list[str]] = {}
        for row in self._active():
            out.setdefault(row.vendor, []).append(self._open(row))
        return out

    def summaries(self) -> dict[str, list[KeySummary]]:
        cutoff = utcnow() - timedelta(days=RETIRED_KEPT_DAYS)
        retired = {
            (vendor, slot)
            for vendor, slot in self._session.execute(
                select(PlatformCredentialRow.vendor, PlatformCredentialRow.slot).where(
                    PlatformCredentialRow.active.is_(False),
                    PlatformCredentialRow.retired_at >= cutoff,
                )
            )
        }
        out: dict[str, list[KeySummary]] = {}
        for row in self._active():
            out.setdefault(row.vendor, []).append(
                KeySummary(
                    row.vendor, row.slot, row.version, row.last4, row.created_at,
                    row.created_by, (row.vendor, row.slot) in retired,
                )
            )  # fmt: skip
        return out

    def _retire(self, vendor: str, slot: int, now: datetime) -> None:
        for row in self._active():
            if row.vendor == vendor and row.slot == slot:
                row.active, row.retired_at = False, now

    def put(self, vendor: str, key: str, *, by: str | None, slot: int = 1) -> int:
        """Make ``key`` the live key in ``slot`` of ``vendor``; the old one is retired."""
        _check_slot(slot)
        now = utcnow()
        latest = self._session.scalar(
            select(func.max(PlatformCredentialRow.version)).where(
                PlatformCredentialRow.vendor == vendor
            )
        )
        self._retire(vendor, slot, now)
        version = (latest or 0) + 1
        sealed = self._keyring.seal(key, _aad(vendor, version))
        self._session.add(
            PlatformCredentialRow(
                vendor=vendor,
                slot=slot,
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

    def add(self, vendor: str, keys: list[str], *, by: str | None) -> list[int]:
        """Add each key in a slot of its own, after every slot the vendor has used (retired
        ones too, so a key in its 30 days can still be rolled back into its own slot). A key
        the vendor already has live is skipped. Returns the slots filled."""
        live = {self._open(r) for r in self._active() if r.vendor == vendor}
        used = self._session.scalar(
            select(func.max(PlatformCredentialRow.slot)).where(
                PlatformCredentialRow.vendor == vendor
            )
        )
        slot = used or 0
        filled: list[int] = []
        for key in keys:
            if key in live:
                continue
            slot += 1
            self.put(vendor, key, by=by, slot=slot)
            live.add(key)
            filled.append(slot)
        return filled

    def roll_back(self, vendor: str, slot: int = 1) -> int:
        """Make the slot's most recently retired key live again, retiring the current one."""
        cutoff = utcnow() - timedelta(days=RETIRED_KEPT_DAYS)
        previous = self._session.scalars(
            select(PlatformCredentialRow)
            .where(
                PlatformCredentialRow.vendor == vendor,
                PlatformCredentialRow.slot == slot,
                PlatformCredentialRow.active.is_(False),
                PlatformCredentialRow.retired_at >= cutoff,
            )
            .order_by(PlatformCredentialRow.version.desc())
        ).first()
        if previous is None:
            raise InvalidInput(f"no earlier key of {vendor} in slot {slot} to go back to")
        self._retire(vendor, slot, utcnow())
        previous.active, previous.retired_at = True, None
        self._session.flush()
        return previous.version

    def remove(self, vendor: str, slot: int) -> None:
        """Take a slot's key out of use. It is retired, so it can be rolled back for 30 days."""
        if not any(r.vendor == vendor and r.slot == slot for r in self._active()):
            raise InvalidInput(f"{vendor} has no key in slot {slot}")
        self._retire(vendor, slot, utcnow())
        self._session.flush()

    def reveal(self, vendor: str, slot: int = 1) -> str:
        for row in self._active():
            if row.vendor == vendor and row.slot == slot:
                return self._open(row)
        raise InvalidInput(f"{vendor} has no key in slot {slot}")

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
