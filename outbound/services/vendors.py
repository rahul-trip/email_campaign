"""Vendor keys and model settings, managed in the admin console (Phase 6d.4).

``effective_settings`` lays what the database holds over the environment's ``Settings``, so the
adapters are built exactly as before; a change reaches the worker the next time a run is
assembled, without a restart. In development and tests, where nothing is in the database, the
environment values stand."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr

from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWork, PlatformUnitOfWorkFactory
from outbound.db.types import utcnow
from outbound.domain.credits import as_credits, milli
from outbound.domain.errors import InvalidInput
from outbound.domain.platform_settings import (
    LLM_PROVIDERS,
    REASONING_EFFORTS,
    LlmModel,
    PlatformSettings,
)
from outbound.domain.vendors import BY_CODE, LLM_FIELDS, MAX_KEYS_PER_ADD, VENDORS, mask
from outbound.logging import get_logger
from outbound.providers.adapters.llm import PRESETS
from outbound.providers.balances import HAS_BALANCE, Balance, balance
from outbound.providers.keycheck import KeyCheck, can_test, check_key

log = get_logger(__name__)

Stamp = tuple[int, tuple[tuple[str, int], ...]]
BALANCE_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class AddedKeys:
    added: int
    already_there: int  # live already, or given twice: not added again


@dataclass(frozen=True)
class KeyView:
    """One live key of a vendor, as the console may show it."""

    slot: int
    key: str  # masked
    version: int
    set_at: datetime
    set_by: str | None
    can_roll_back: bool


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
    credits_milli: int  # AI credits used this calendar month, in thousandths
    cost_micro_usd: int  # what those calls cost the platform this month
    cap_credits: int | None  # AI credits a month
    key_refusals: int  # calls the vendor refused our key for in the last day
    can_test: bool
    keys: list[KeyView]  # every live key in the database, in slot order
    # What the vendor says the account has left (None: no balance call, or it failed).
    balance: float | None = None
    balance_unit: str = ""
    balance_note: str = ""
    paused_for_credit: bool = False  # paused by itself because the account ran out


class VendorService:
    def __init__(
        self,
        platform: PlatformUnitOfWorkFactory,
        base: Settings,
        *,
        now: Callable[[], datetime] = utcnow,
        balance_of: Callable[[str, str], Balance | None] = balance,
    ) -> None:
        self._balance_of = balance_of
        self._balances: dict[str, Balance | None] = {}
        self._balances_at: datetime | None = None
        self._balance_lock = threading.Lock()
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
        pools: dict[str, list[SecretStr]] = {}
        for vendor in VENDORS:
            if vendor.code in platform_settings.paused_vendors:
                update[vendor.setting] = SecretStr("")
            elif vendor.code in keys:
                update[vendor.setting] = SecretStr(keys[vendor.code][0])
                if len(keys[vendor.code]) > 1:
                    pools[vendor.code] = [SecretStr(k) for k in keys[vendor.code]]
        update |= _model_update(platform_settings, keys, pools)
        update["vendor_key_pools"] = pools
        update["finder_chain"] = [
            f for f in self._base.finder_chain if f not in platform_settings.paused_vendors
        ]
        return self._base.model_copy(update=update), stamp

    # ------------------------------------------------------------------ the console

    def _env_key(self, code: str) -> str:
        return str(getattr(self._base, BY_CODE[code].setting).get_secret_value())

    def balances(self, *, refresh: bool = False) -> dict[str, Balance | None]:
        """What each vendor with a balance call says is left. The calls are free; the answer is
        kept for ten minutes, so opening the console does not ask every time."""
        with self._balance_lock:
            if not self._base.vendor_balance_checks:
                return {}
            fresh = self._balances_at is not None and self._now() - self._balances_at < BALANCE_TTL
            if fresh and not refresh:
                return dict(self._balances)
            with self._platform() as p:
                stored = p.vendor_keys.current()
            # A paused vendor's key is still read: that is how we see it has credit again.
            keys = {code: (stored.get(code) or [self._env_key(code)])[0] for code in HAS_BALANCE}
            with ThreadPoolExecutor(max_workers=len(keys)) as pool:
                answers = pool.map(lambda code: self._balance_of(code, keys[code]), keys)
                found = dict(zip(keys, answers, strict=True))
            self._balances, self._balances_at = found, self._now()
            return dict(found)

    def handle_credit(self) -> tuple[list[str], list[str]]:
        """Pause finders whose account ran out of credit, and resume the ones that have credit
        again. Returns (paused, resumed). Run from the worker.

        A finder is paused when its balance is zero, or when the balance cannot be read and the
        vendor refused a call for lack of credit in the last hour. A finder is resumed when its
        balance shows credit. Only finders: pausing the verifier would stop every lead. A vendor
        staff paused by hand is never resumed here.
        """
        balances = self.balances(refresh=True)
        with self._platform() as p:
            current, _ = p.settings.get()
            refused = p.figures.key_failures(self._now() - timedelta(hours=1), "BudgetExceeded")
            stored = p.vendor_keys.current()
        paused: list[str] = []
        for vendor in VENDORS:
            if vendor.role != "finder" or vendor.code in current.paused_vendors:
                continue
            seen = balances.get(vendor.code)
            empty = seen.empty if seen is not None else refused.get(vendor.code, 0) > 0
            if empty and (stored.get(vendor.code) or self._env_key(vendor.code)):
                paused.append(vendor.code)
        resumed = []
        for code in sorted(current.paused_for_credit):
            seen = balances.get(code)
            if seen is not None and not seen.empty:
                resumed.append(code)
        if not paused and not resumed:
            return [], []
        with self._platform() as p:
            current, version = p.settings.get()
            p.settings.save(
                replace(
                    current,
                    paused_vendors=(current.paused_vendors | set(paused)) - set(resumed),
                    paused_for_credit=(current.paused_for_credit | set(paused)) - set(resumed),
                ),
                expected_version=version,
            )
            for action, codes in (("paused_for_credit", paused), ("resumed_with_credit", resumed)):
                for code in codes:
                    seen = balances.get(code)
                    p.audit.record(
                        f"vendor_{action}", actor_user_id=None, target_type="vendor",
                        target_id=code, data={"balance": seen.label() if seen else None},
                    )  # fmt: skip
            p.commit()
        log.warning("vendors_credit_handled", paused=paused, resumed=resumed)
        return paused, resumed

    def statuses(self) -> list[VendorStatus]:
        balances = self.balances()
        with self._platform() as p:
            settings, _ = p.settings.get()
            stored = p.vendor_keys.summaries()
            spent = self._spend(p)
            cost = self._spend(p, dollars=True)
            refused = self._refusals(p)
        out: list[VendorStatus] = []
        for vendor in VENDORS:
            live = stored.get(vendor.code, [])
            found = live[0] if live else None
            env = getattr(self._base, vendor.setting).get_secret_value()
            if found:
                key, source, version = mask(found.last4), "database", found.version
            elif env:
                key, source, version = mask(env[-4:]), "environment", 0
            else:
                key, source, version = mask(""), "none", 0
            seen = balances.get(vendor.code)
            out.append(
                VendorStatus(
                    vendor.code, vendor.name, vendor.role, key, source, version,
                    found.set_at if found else None, found.set_by if found else None,
                    vendor.code in settings.paused_vendors,
                    any(k.can_roll_back for k in live),
                    spent.get(vendor.code, 0), cost.get(vendor.code, 0),
                    settings.vendor_caps.get(vendor.code),
                    refused.get(vendor.code, 0), can_test(vendor.code),
                    [
                        KeyView(k.slot, mask(k.last4), k.version, k.set_at, k.set_by,
                                k.can_roll_back)
                        for k in live
                    ],
                    seen.remaining if seen else None,
                    seen.unit if seen else "",
                    seen.note if seen else "",
                    vendor.code in settings.paused_for_credit,
                )
            )  # fmt: skip
        return out

    def set_cap(self, vendor: str, cap_credits: int | None, *, by: str | None) -> None:
        """A monthly cap for a vendor in AI credits; ``None`` removes it. See ``enforce_caps``."""
        _known(vendor)
        if cap_credits is not None and cap_credits < 0:
            raise InvalidInput("a cap cannot be negative")
        with self._platform() as p:
            current, version = p.settings.get()
            caps = {k: v for k, v in current.vendor_caps.items() if k != vendor}
            if cap_credits is not None:
                caps[vendor] = cap_credits
            p.settings.save(replace(current, vendor_caps=caps), expected_version=version)
            p.audit.record(
                "vendor_cap_set", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"cap_credits": cap_credits},
            )  # fmt: skip
            p.commit()

    def enforce_caps(self) -> list[str]:
        """Pause every vendor whose calls used its monthly cap of AI credits. Returns the ones
        paused now; a person resumes them (after raising the cap, or next month). Run from the
        worker."""
        paused: list[str] = []
        with self._platform() as p:
            current, version = p.settings.get()
            spent = self._spend(p)
            over = [
                code
                for code, cap in current.vendor_caps.items()
                if spent.get(code, 0) >= milli(cap) and code not in current.paused_vendors
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
                    target_id=code, data={"credits": as_credits(spent.get(code, 0))},
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
        self,
        vendor: str,
        *,
        by: str | None,
        slot: int = 1,
        client: httpx.Client | None = None,
    ) -> KeyCheck:
        """One small real call with the slot's key as stored (even if the vendor is paused).
        Slot 1 with nothing stored tests the environment's key."""
        _known(vendor)
        with self._platform() as p:
            platform_settings, _ = p.settings.get()
            stored = next(
                (
                    p.vendor_keys.reveal(vendor, slot)
                    for k in p.vendor_keys.summaries().get(vendor, [])
                    if k.slot == slot
                ),
                None,
            )
        if stored is None and slot != 1:
            raise InvalidInput(f"{vendor} has no key in slot {slot}")
        update: dict[str, Any] = dict(platform_settings.llm)
        if stored is not None:
            update[BY_CODE[vendor].setting] = SecretStr(stored)
        result = check_key(vendor, self._base.model_copy(update=update), client)
        with self._platform() as p:
            p.audit.record(
                "vendor_key_tested", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"ok": result.ok, "slot": slot},
            )  # fmt: skip
            p.commit()
        return result

    def _spend(self, p: PlatformUnitOfWork, *, dollars: bool = False) -> dict[str, int]:
        """This month's AI credits (thousandths) per vendor, or with ``dollars`` what the calls
        cost the platform (micro-USD). The language model's ledger name is its provider preset,
        so it is whatever no other vendor claims."""
        now = self._now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        sums = p.figures.cost_by_provider if dollars else p.figures.spend_by_provider
        ledger = sums(start, start + timedelta(days=32))
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

    def replace_key(self, vendor: str, key: str, *, by: str | None, slot: int = 1) -> int:
        """Set the key in ``slot`` (1 or more); a vendor with several keys uses one at random
        for each call."""
        _known(vendor)
        key = key.strip()
        if len(key) < 8:
            raise InvalidInput("that does not look like an API key")
        with self._platform() as p:
            version = p.vendor_keys.put(vendor, key, by=by, slot=slot)
            p.audit.record(
                "vendor_key_replaced", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"version": version, "slot": slot},
            )  # fmt: skip
            p.commit()
        log.info("vendor_key_replaced", vendor=vendor, version=version, slot=slot)
        return version

    def add_keys(self, vendor: str, keys: list[str], *, by: str | None) -> AddedKeys:
        """Add every key, each in a new slot; there is no limit on how many a vendor has. Blank
        lines are ignored, and a key given twice or already live is added once."""
        _known(vendor)
        wanted = list(dict.fromkeys(k.strip() for k in keys if k.strip()))
        if not wanted:
            raise InvalidInput("paste at least one key")
        if len(wanted) > MAX_KEYS_PER_ADD:
            raise InvalidInput(f"add at most {MAX_KEYS_PER_ADD} keys at a time")
        short = [n for n, k in enumerate(wanted, start=1) if len(k) < 8]
        if short:
            raise InvalidInput(f"key {short[0]} does not look like an API key")
        with self._platform() as p:
            slots = p.vendor_keys.add(vendor, wanted, by=by)
            if slots:
                p.audit.record(
                    "vendor_keys_added", actor_user_id=by, target_type="vendor",
                    target_id=vendor, data={"slots": slots},
                )  # fmt: skip
            p.commit()
        log.info("vendor_keys_added", vendor=vendor, added=len(slots))
        return AddedKeys(added=len(slots), already_there=len(wanted) - len(slots))

    def remove_key(self, vendor: str, slot: int, *, by: str | None) -> None:
        """Stop using the slot's key. It is retired, so it can be rolled back for 30 days."""
        _known(vendor)
        with self._platform() as p:
            p.vendor_keys.remove(vendor, slot)
            p.audit.record(
                "vendor_key_removed", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"slot": slot},
            )  # fmt: skip
            p.commit()
        log.info("vendor_key_removed", vendor=vendor, slot=slot)

    def roll_back(self, vendor: str, *, by: str | None, slot: int = 1) -> int:
        _known(vendor)
        with self._platform() as p:
            version = p.vendor_keys.roll_back(vendor, slot)
            p.audit.record(
                "vendor_key_rolled_back", actor_user_id=by, target_type="vendor",
                target_id=vendor, data={"version": version, "slot": slot},
            )  # fmt: skip
            p.commit()
        return version

    def reveal(self, vendor: str, *, by: str | None, slot: int = 1) -> str:
        """The key in full. Written to the audit log every time."""
        _known(vendor)
        with self._platform() as p:
            key = p.vendor_keys.reveal(vendor, slot)
            p.audit.record(
                "vendor_key_revealed", actor_user_id=by, target_type="vendor", target_id=vendor,
                data={"slot": slot},
            )  # fmt: skip
            p.commit()
        return key

    def pause(self, vendor: str, paused: bool, *, by: str | None) -> None:
        _known(vendor)
        with self._platform() as p:
            current, version = p.settings.get()
            names = set(current.paused_vendors)
            names.add(vendor) if paused else names.discard(vendor)
            # A person's choice replaces the automatic one either way.
            p.settings.save(
                replace(
                    current,
                    paused_vendors=frozenset(names),
                    paused_for_credit=current.paused_for_credit - {vendor},
                ),
                expected_version=version,
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

    def llm_charges(self) -> dict[str, tuple[float, float]]:
        """What each model's calls use, in AI credits per million input and output tokens."""
        with self._platform() as p:
            current, _ = p.settings.get()
        return dict(current.llm_charges)

    def set_llm_charges(self, charges: dict[str, tuple[float, float]], *, by: str | None) -> None:
        """Replace the charges for model calls. A model with no charge uses its dollar price
        (``LLM_PRICES``), and none is configured by default, so its calls would use no credits."""
        clean: dict[str, tuple[float, float]] = {}
        for model, (per_in, per_out) in charges.items():
            name = model.strip()
            if not name:
                raise InvalidInput("each charge needs a model name")
            if per_in < 0 or per_out < 0:
                raise InvalidInput("a charge cannot be negative")
            clean[name] = (float(per_in), float(per_out))
        with self._platform() as p:
            current, version = p.settings.get()
            p.settings.save(replace(current, llm_charges=clean), expected_version=version)
            p.audit.record(
                "llm_charges_changed", actor_user_id=by, target_type="vendor", target_id="llm",
                data={model: list(rate) for model, rate in clean.items()},
            )  # fmt: skip
            p.commit()

    # ------------------------------------------------------------------ models

    def models(self) -> tuple[PlatformSettings, dict[str, str]]:
        """The settings (catalog, default, writer) and each model's key, masked."""
        with self._platform() as p:
            current, _ = p.settings.get()
            stored = p.vendor_keys.summaries()
        keys = {
            code: mask(stored[m.key_name][0].last4) if stored.get(m.key_name) else ""
            for code, m in current.models.items()
        }
        return current, keys

    def save_model(self, model: LlmModel, *, api_key: str | None, by: str | None) -> None:
        """Add a model or change one. ``api_key`` None keeps the stored key; "" removes it."""
        _check_model(model)
        with self._platform() as p:
            current, version = p.settings.get()
            has_key = bool(p.vendor_keys.summaries().get(model.key_name))
            if api_key:  # a model with no key of its own uses the Language model vendor's key
                if len(api_key.strip()) < 8:
                    raise InvalidInput("that does not look like an API key")
                p.vendor_keys.put(model.key_name, api_key.strip(), by=by)
                has_key = True
            elif api_key == "" and has_key:
                p.vendor_keys.remove(model.key_name, 1)
                has_key = False
            models = {**current.models, model.code: model}
            p.settings.save(replace(current, models=models), expected_version=version)
            p.audit.record(
                "model_saved", actor_user_id=by, target_type="model", target_id=model.code,
                data={"provider": model.provider, "model": model.model,
                      "base_url": model.base_url, "key_changed": api_key is not None},
            )  # fmt: skip
            p.commit()

    def remove_model(self, code: str, *, by: str | None) -> None:
        with self._platform() as p:
            current, version = p.settings.get()
            if code not in current.models:
                raise InvalidInput(f"there is no model {code!r}")
            if code in (current.default_model, current.writer_model, current.extract_model):
                raise InvalidInput(
                    "choose another default (writer, extraction) model before removing it"
                )
            if p.vendor_keys.summaries().get(f"model:{code}"):
                p.vendor_keys.remove(f"model:{code}", 1)
            models = {k: v for k, v in current.models.items() if k != code}
            p.settings.save(replace(current, models=models), expected_version=version)
            p.audit.record(
                "model_removed", actor_user_id=by, target_type="model", target_id=code
            )  # fmt: skip
            p.commit()

    def choose_models(
        self, default: str, writer: str, extractor: str = "", *, by: str | None
    ) -> None:
        """The model every call uses, the one that writes emails and the one that reads sites,
        news and people in research ("": the default). An empty default goes back to the LLM_*
        settings."""
        with self._platform() as p:
            current, version = p.settings.get()
            for code in (default, writer, extractor):
                if code and code not in current.models:
                    raise InvalidInput(f"there is no model {code!r}")
            if (writer or extractor) and not default:
                raise InvalidInput("choose a default model before a writer or extraction model")
            chosen = current.models.get(default)
            if (
                chosen is not None
                and PRESETS[chosen.provider].needs_key
                and not p.vendor_keys.summaries().get(chosen.key_name)
                and not self._fallback_key()
            ):
                raise InvalidInput(f"{chosen.label} has no API key: add one before choosing it")
            for role, code in (("writer", writer), ("extraction", extractor)):
                if code and default:
                    one, two = current.models[default], current.models[code]
                    if (one.provider, one.base_url) != (two.provider, two.base_url):
                        raise InvalidInput(
                            f"the {role} model must use the same provider and address "
                            "as the default"
                        )
            p.settings.save(
                replace(
                    current, default_model=default, writer_model=writer, extract_model=extractor
                ),
                expected_version=version,
            )
            p.audit.record(
                "models_chosen", actor_user_id=by, target_type="model", target_id=default or None,
                data={"default": default, "writer": writer, "extraction": extractor},
            )  # fmt: skip
            p.commit()

    def test_model(
        self, code: str, *, by: str | None, client: httpx.Client | None = None
    ) -> KeyCheck:
        """One tiny real call to the model, with its own settings and key."""
        with self._platform() as p:
            current, _ = p.settings.get()
            if code not in current.models:
                raise InvalidInput(f"there is no model {code!r}")
            keys = p.vendor_keys.current()
        trial = replace(current, default_model=code, writer_model="", extract_model="")
        update: dict[str, Any] = {**current.llm, **_model_update(trial, keys, {})}
        if "llm" in keys and "llm_api_key" not in update:
            update["llm_api_key"] = SecretStr(keys["llm"][0])
        result = check_key("llm", self._base.model_copy(update=update), client)
        with self._platform() as p:
            p.audit.record(
                "model_tested", actor_user_id=by, target_type="model", target_id=code,
                data={"ok": result.ok},
            )  # fmt: skip
            p.commit()
        return result

    def _fallback_key(self) -> bool:
        """Whether a model without its own key can use the Language model vendor's key."""
        with self._platform() as p:
            stored = p.vendor_keys.summaries()
        return bool(stored.get("llm")) or bool(self._base.llm_api_key.get_secret_value())

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


# Where each provider's own key lives in the settings (``providers/registry.py::_llm``).
_PROVIDER_KEY = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "github_copilot": "copilot_api_key",
}


def _model_update(
    settings: PlatformSettings, keys: dict[str, list[str]], pools: dict[str, list[SecretStr]]
) -> dict[str, Any]:
    """The LLM_* settings the chosen default (and writer) model stands for. Empty when no model
    is chosen. A model with its own key replaces the Language model vendor's key and pool."""
    chosen = settings.models.get(settings.default_model)
    if chosen is None:
        return {}
    writer = settings.models.get(settings.writer_model)
    extractor = settings.models.get(settings.extract_model)
    update: dict[str, Any] = {
        "llm_provider": chosen.provider,
        "llm_model": chosen.model,
        "llm_base_url": chosen.base_url,
        "llm_temperature": chosen.temperature,
        "llm_max_tokens": chosen.max_tokens,
        "llm_reasoning_effort": chosen.reasoning_effort,
        "llm_copy_model": writer.model if writer else "",
        "llm_extract_model": extractor.model if extractor else "",
    }
    own = keys.get(chosen.key_name)
    if own and "llm" not in settings.paused_vendors:
        key = SecretStr(own[0])
        update["llm_api_key"] = key
        if chosen.provider in _PROVIDER_KEY:
            update[_PROVIDER_KEY[chosen.provider]] = key
        pools.pop("llm", None)
    return update


def _check_model(model: LlmModel) -> None:
    code = model.code.strip()
    if not code or not code.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise InvalidInput("a model code is letters, digits, '.', '-' and '_'")
    if code == "default":
        raise InvalidInput("'default' cannot be a model code")
    if model.provider not in LLM_PROVIDERS:
        raise InvalidInput(f"the provider must be one of {', '.join(LLM_PROVIDERS)}")
    if not model.model.strip():
        raise InvalidInput("say the provider's name for the model")
    if model.provider == "openai_compatible" and not model.base_url.strip():
        raise InvalidInput("an OpenAI-compatible model needs its base URL")
    if model.base_url and not model.base_url.startswith(("https://", "http://")):
        raise InvalidInput("the base URL must start with https:// (or http:// for a local one)")
    if model.reasoning_effort not in REASONING_EFFORTS:
        raise InvalidInput("reasoning effort is low, medium, high or none")
    if not 0 <= model.temperature <= 2:
        raise InvalidInput("temperature is between 0 and 2")
    if not 16 <= model.max_tokens <= 200_000:
        raise InvalidInput("max tokens is between 16 and 200,000")
    if model.input_credits < 0 or model.output_credits < 0:
        raise InvalidInput("a charge cannot be negative")
