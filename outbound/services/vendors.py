"""Vendor keys and model settings, managed in the admin console (Phase 6d.4).

``effective_settings`` lays what the database holds over the environment's ``Settings``, so the
adapters are built exactly as before; a change reaches the worker the next time a run is
assembled, without a restart. In development and tests, where nothing is in the database, the
environment values stand."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr

from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWork, PlatformUnitOfWorkFactory
from outbound.db.types import utcnow
from outbound.domain.errors import InvalidInput
from outbound.domain.vendors import BY_CODE, LLM_FIELDS, VENDORS, mask
from outbound.logging import get_logger
from outbound.providers.keycheck import KeyCheck, can_test, check_key

log = get_logger(__name__)

Stamp = tuple[int, tuple[tuple[str, int], ...]]


@dataclass(frozen=True)
class VendorStatus:
    code: str
    name: str
    role: str
    key: str  # masked
    source: str  # database, environment or none
    version: int
    set_at: datetime | None
    set_by: str | None
    paused: bool
    can_roll_back: bool
    spend_micro_usd: int  # this calendar month
    cap_micro_usd: int | None
    key_refusals: int  # calls the vendor refused our key for in the last day
    can_test: bool


class VendorService:
    def __init__(
        self,
        platform: PlatformUnitOfWorkFactory,
        base: Settings,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._platform = platform
        self._base = base
        self._now = now

    # ------------------------------------------------------------------ what is live

    def stamp(self) -> Stamp:
        with self._platform() as p:
            _, version = p.settings.get()
            return version, p.vendor_keys.stamp()

    def effective_settings(self) -> tuple[Settings, Stamp]:
        with self._platform() as p:
            platform_settings, version = p.settings.get()
            keys = p.vendor_keys.current()
            stamp: Stamp = (version, p.vendor_keys.stamp())
        update: dict[str, Any] = dict(platform_settings.llm)
        for vendor in VENDORS:
            if vendor.code in platform_settings.paused_vendors:
                update[vendor.setting] = SecretStr("")
            elif vendor.code in keys:
                update[vendor.setting] = SecretStr(keys[vendor.code])
        update["finder_chain"] = [
            f for f in self._base.finder_chain if f not in platform_settings.paused_vendors
        ]
        return self._base.model_copy(update=update), stamp

    # ------------------------------------------------------------------ the console

    def statuses(self) -> list[VendorStatus]:
        with self._platform() as p:
            settings, _ = p.settings.get()
            stored = p.vendor_keys.summaries()
            spent = self._spend(p)
            refused = self._refusals(p)
        out: list[VendorStatus] = []
        for vendor in VENDORS:
            found = stored.get(vendor.code)
            env = getattr(self._base, vendor.setting).get_secret_value()
            if found:
                key, source, version = mask(found.last4), "database", found.version
            elif env:
                key, source, version = mask(env[-4:]), "environment", 0
            else:
                key, source, version = mask(""), "none", 0
            out.append(
                VendorStatus(
                    vendor.code, vendor.name, vendor.role, key, source, version,
                    found.set_at if found else None, found.set_by if found else None,
                    vendor.code in settings.paused_vendors,
                    bool(found and found.can_roll_back),
                    spent.get(vendor.code, 0), settings.vendor_caps.get(vendor.code),
                    refused.get(vendor.code, 0), can_test(vendor.code),
                )
            )  # fmt: skip
        return out

    def set_cap(self, vendor: str, cap_micro_usd: int | None, *, by: str | None) -> None:
        """A monthly spend cap for a vendor; ``None`` removes it. See ``enforce_caps``."""
        _known(vendor)
        if cap_micro_usd is not None and cap_micro_usd < 0:
            raise InvalidInput("a cap cannot be negative")
        with self._platform() as p:
            current, version = p.settings.get()
            caps = {k: v for k, v in current.vendor_caps.items() if k != vendor}
            if cap_micro_usd is not None:
                caps[vendor] = cap_micro_usd
            p.settings.save(replace(current, vendor_caps=caps), expected_version=version)
            p.audit.record(
                "vendor_cap_set", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"cap_micro_usd": cap_micro_usd},
            )  # fmt: skip
            p.commit()

    def enforce_caps(self) -> list[str]:
        """Pause every vendor that has spent its monthly cap. Returns the ones paused now; a
        person resumes them (after raising the cap, or next month). Run from the worker."""
        paused: list[str] = []
        with self._platform() as p:
            current, version = p.settings.get()
            spent = self._spend(p)
            over = [
                code
                for code, cap in current.vendor_caps.items()
                if spent.get(code, 0) >= cap and code not in current.paused_vendors
            ]
            if not over:
                return []
            p.settings.save(
                replace(current, paused_vendors=current.paused_vendors | frozenset(over)),
                expected_version=version,
            )
            for code in over:
                p.audit.record(
                    "vendor_paused_by_cap", actor_user_id=None, target_type="vendor",
                    target_id=code, data={"spend_micro_usd": spent.get(code, 0)},
                )  # fmt: skip
                paused.append(code)
            p.commit()
        log.warning("vendors_paused_by_cap", vendors=paused)
        return paused

    def _refusals(self, p: PlatformUnitOfWork) -> dict[str, int]:
        """Calls refused for a bad key in the last day, per vendor (the model's ledger name is
        its provider preset, so it is whatever no other vendor claims)."""
        found = p.figures.key_failures(self._now() - timedelta(days=1))
        out = {code: n for code, n in found.items() if code in BY_CODE}
        out["llm"] = sum(n for name, n in found.items() if name not in BY_CODE)
        return out

    def test_key(
        self, vendor: str, *, by: str | None, client: httpx.Client | None = None
    ) -> KeyCheck:
        """One small real call with the key as stored (even if the vendor is paused)."""
        _known(vendor)
        with self._platform() as p:
            platform_settings, _ = p.settings.get()
            stored = p.vendor_keys.current().get(vendor)
        update: dict[str, Any] = dict(platform_settings.llm)
        if stored is not None:
            update[BY_CODE[vendor].setting] = SecretStr(stored)
        result = check_key(vendor, self._base.model_copy(update=update), client)
        with self._platform() as p:
            p.audit.record(
                "vendor_key_tested", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"ok": result.ok},
            )  # fmt: skip
            p.commit()
        return result

    def _spend(self, p: PlatformUnitOfWork) -> dict[str, int]:
        """This month's cost per vendor. The language model's ledger name is its provider
        preset, so it is whatever no other vendor claims."""
        now = self._now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ledger = p.figures.spend_by_provider(start, start + timedelta(days=32))
        spent = {code: total for code, total in ledger.items() if code in BY_CODE}
        spent["llm"] = sum(
            t for name, t in ledger.items() if name not in BY_CODE and name != "directory"
        )
        return spent

    def llm_settings(self) -> dict[str, Any]:
        """The LLM settings as they are now: the environment's, with the database's on top."""
        with self._platform() as p:
            overrides, _ = p.settings.get()
        return {name: getattr(self._base, name) for name in LLM_FIELDS} | overrides.llm

    def replace_key(self, vendor: str, key: str, *, by: str | None) -> int:
        _known(vendor)
        key = key.strip()
        if len(key) < 8:
            raise InvalidInput("that does not look like an API key")
        with self._platform() as p:
            version = p.vendor_keys.put(vendor, key, by=by)
            p.audit.record(
                "vendor_key_replaced", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"version": version},
            )  # fmt: skip
            p.commit()
        log.info("vendor_key_replaced", vendor=vendor, version=version)
        return version

    def roll_back(self, vendor: str, *, by: str | None) -> int:
        _known(vendor)
        with self._platform() as p:
            version = p.vendor_keys.roll_back(vendor)
            p.audit.record(
                "vendor_key_rolled_back", actor_user_id=by, target_type="vendor",
                target_id=vendor, data={"version": version},
            )  # fmt: skip
            p.commit()
        return version

    def reveal(self, vendor: str, *, by: str | None) -> str:
        """The key in full. Written to the audit log every time."""
        _known(vendor)
        with self._platform() as p:
            key = p.vendor_keys.reveal(vendor)
            p.audit.record(
                "vendor_key_revealed", actor_user_id=by, target_type="vendor", target_id=vendor
            )
            p.commit()
        return key

    def pause(self, vendor: str, paused: bool, *, by: str | None) -> None:
        _known(vendor)
        with self._platform() as p:
            current, version = p.settings.get()
            names = set(current.paused_vendors)
            names.add(vendor) if paused else names.discard(vendor)
            p.settings.save(
                replace(current, paused_vendors=frozenset(names)), expected_version=version
            )
            p.audit.record(
                "vendor_paused" if paused else "vendor_resumed", actor_user_id=by,
                target_type="vendor", target_id=vendor,
            )  # fmt: skip
            p.commit()

    def update_llm(self, changes: dict[str, Any], *, by: str | None) -> None:
        unknown = set(changes) - set(LLM_FIELDS)
        if unknown:
            raise InvalidInput(f"cannot change {sorted(unknown)}")
        for name, value in changes.items():
            kind = LLM_FIELDS[name]
            if not isinstance(value, kind) and not (kind is float and isinstance(value, int)):
                raise InvalidInput(f"{name} must be a {kind.__name__}")
        with self._platform() as p:
            current, version = p.settings.get()
            p.settings.save(
                replace(current, llm={**current.llm, **changes}), expected_version=version
            )
            p.audit.record(
                "llm_settings_changed", actor_user_id=by, target_type="vendor", target_id="llm",
                data=changes,
            )  # fmt: skip
            p.commit()

    def import_env(self, *, by: str | None = None) -> list[str]:
        """Copy the environment's keys into the database, once. A vendor that already has a key
        there is left alone. Returns the vendors copied."""
        copied: list[str] = []
        with self._platform() as p:
            stored = p.vendor_keys.summaries()
            for vendor in VENDORS:
                key = getattr(self._base, vendor.setting).get_secret_value()
                if key and vendor.code not in stored:
                    p.vendor_keys.put(vendor.code, key, by=by)
                    copied.append(vendor.code)
            if copied:
                p.audit.record("vendor_keys_imported", actor_user_id=by, data={"vendors": copied})
            p.commit()
        return copied


class LiveProviders[T]:
    """The vendor adapters, rebuilt whenever a key or a model setting changed. ``get`` is cheap
    when nothing did: it compares a version stamp."""

    def __init__(self, service: VendorService, build: Callable[[Settings], T]) -> None:
        self._service = service
        self._build = build
        self._lock = threading.Lock()
        self._stamp: Stamp | None = None
        self._providers: T | None = None

    def get(self) -> T:
        stamp = self._service.stamp()
        with self._lock:
            providers = self._providers
            if stamp != self._stamp or providers is None:
                settings, stamp = self._service.effective_settings()
                providers = self._providers = self._build(settings)
                self._stamp = stamp
                log.info("vendors_reloaded")
            return providers


def _known(vendor: str) -> None:
    if vendor not in BY_CODE:
        raise InvalidInput(f"unknown vendor {vendor!r}")
