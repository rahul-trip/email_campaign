"""The platform's own settings (Phase 6d): the plan catalog and the switches only platform
admins touch. Kept as one JSON document; reading is tolerant (unknown keys are ignored, missing
ones take their defaults) so a newer or older version of the code can share a database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from outbound.domain.credits import DEFAULT_CREDIT_VALUE_MICRO_USD
from outbound.domain.entitlements import DEFAULT_PLANS, FREE, UNLIMITED, Plan
from outbound.domain.vendors import LLM_FIELDS

DEFAULTS_BY_CODE = {p.code: p for p in DEFAULT_PLANS}


@dataclass(frozen=True)
class PlatformSettings:
    plans: dict[str, Plan] = field(default_factory=lambda: dict(DEFAULTS_BY_CODE))
    default_plan: str = FREE.code
    # How much vendor and model cost one AI credit stands for (``domain.credits``). Superadmins
    # only; changing it applies to calls made from then on.
    credit_value_micro_usd: int = DEFAULT_CREDIT_VALUE_MICRO_USD
    kill_runs: bool = False  # nothing runs for anyone
    kill_drafts: bool = False  # nothing is saved to a mailbox for anyone
    superadmin_enabled: bool = True  # alpha only
    announcement: str = ""  # shown in every workspace
    paused_vendors: frozenset[str] = frozenset()  # their keys are ignored until resumed
    llm: dict[str, Any] = field(default_factory=dict)  # overrides of the LLM_* settings
    vendor_caps: dict[str, int] = field(default_factory=dict)  # AI credits a month, per vendor
    # What each model's calls use: model -> (AI credits per million input tokens, per million
    # output tokens). Set in the console's Language model card; applies from then on.
    llm_charges: dict[str, tuple[float, float]] = field(default_factory=dict)

    def plan(self, code: str) -> Plan:
        """The plan with this code; the default plan if it was removed from the catalog."""
        if code == UNLIMITED.code:
            return UNLIMITED
        return self.plans.get(code) or self.plans.get(self.default_plan) or FREE


def plan_to_json(plan: Plan) -> dict[str, Any]:
    return {
        "code": plan.code,
        "name": plan.name,
        "monthly_credits": plan.monthly_credits,
        "seats": plan.seats,
        "mailboxes": plan.mailboxes,
        "active_campaigns": plan.active_campaigns,
        "max_leads_per_run": plan.max_leads_per_run,
        "max_prospect_budget_credits": plan.max_prospect_budget_credits,
        "features": sorted(plan.features),
        "access_days": plan.access_days,
    }


def _credits(micro_usd: Any) -> int | None:
    """A dollar figure saved before credits (micro-USD) at the default rate, rounded up."""
    if micro_usd is None:
        return None
    return -(-int(micro_usd) // DEFAULT_CREDIT_VALUE_MICRO_USD)


def plan_from_json(data: dict[str, Any]) -> Plan:
    code = str(data["code"])
    base = DEFAULTS_BY_CODE.get(code, FREE)

    def number(key: str, default: int | None) -> int | None:
        return int(data[key]) if data.get(key) is not None else (None if key in data else default)

    budget = (
        number("max_prospect_budget_credits", base.max_prospect_budget_credits)
        if "max_prospect_budget_credits" in data or "max_prospect_budget_micro_usd" not in data
        else _credits(data["max_prospect_budget_micro_usd"])  # saved before credits
    )
    return Plan(
        code=code,
        name=str(data.get("name") or code),
        monthly_credits=number("monthly_credits", base.monthly_credits),
        seats=number("seats", base.seats),
        mailboxes=number("mailboxes", base.mailboxes),
        active_campaigns=number("active_campaigns", base.active_campaigns),
        max_leads_per_run=number("max_leads_per_run", base.max_leads_per_run),
        max_prospect_budget_credits=budget,
        features=frozenset(str(f) for f in data.get("features", base.features)),
        access_days=number("access_days", base.access_days),
    )


def to_json(settings: PlatformSettings) -> dict[str, Any]:
    return {
        "plans": [plan_to_json(p) for p in settings.plans.values()],
        "default_plan": settings.default_plan,
        "credit_value_micro_usd": settings.credit_value_micro_usd,
        "kill_runs": settings.kill_runs,
        "kill_drafts": settings.kill_drafts,
        "superadmin_enabled": settings.superadmin_enabled,
        "announcement": settings.announcement,
        "paused_vendors": sorted(settings.paused_vendors),
        "llm": settings.llm,
        "vendor_caps_credits": settings.vendor_caps,
        "llm_charges": {model: list(rate) for model, rate in settings.llm_charges.items()},
    }


def from_json(data: dict[str, Any]) -> PlatformSettings:
    defaults = PlatformSettings()
    plans = {p.code: p for p in (plan_from_json(d) for d in data.get("plans", []) if "code" in d)}
    if "vendor_caps_credits" in data:
        caps = {str(k): int(v) for k, v in (data.get("vendor_caps_credits") or {}).items()}
    else:  # saved before credits, in micro-USD
        caps = {str(k): _credits(v) or 0 for k, v in (data.get("vendor_caps") or {}).items()}
    value = data.get("credit_value_micro_usd")
    return PlatformSettings(
        plans=plans or defaults.plans,
        default_plan=str(data.get("default_plan") or defaults.default_plan),
        credit_value_micro_usd=int(value) if value else defaults.credit_value_micro_usd,
        kill_runs=bool(data.get("kill_runs", False)),
        kill_drafts=bool(data.get("kill_drafts", False)),
        superadmin_enabled=bool(data.get("superadmin_enabled", True)),
        announcement=str(data.get("announcement") or ""),
        paused_vendors=frozenset(str(v) for v in data.get("paused_vendors", [])),
        llm={str(k): v for k, v in (data.get("llm") or {}).items() if k in LLM_FIELDS},
        vendor_caps=caps,
        llm_charges={
            str(model): (float(rate[0]), float(rate[1]))
            for model, rate in (data.get("llm_charges") or {}).items()
            if isinstance(rate, list | tuple) and len(rate) == 2
        },
    )
