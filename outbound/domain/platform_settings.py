"""The platform's own settings (Phase 6d): the plan catalog and the switches only platform
admins touch. Kept as one JSON document; reading is tolerant (unknown keys are ignored, missing
ones take their defaults) so a newer or older version of the code can share a database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from outbound.domain.entitlements import FREE, UNLIMITED, Plan
from outbound.domain.enums import UsageStep
from outbound.domain.vendors import LLM_FIELDS


@dataclass(frozen=True)
class PlatformSettings:
    plans: dict[str, Plan] = field(default_factory=lambda: {FREE.code: FREE})
    default_plan: str = FREE.code
    kill_runs: bool = False  # nothing runs for anyone
    kill_drafts: bool = False  # nothing is saved to a mailbox for anyone
    superadmin_enabled: bool = True  # alpha only
    announcement: str = ""  # shown in every workspace
    paused_vendors: frozenset[str] = frozenset()  # their keys are ignored until resumed
    llm: dict[str, Any] = field(default_factory=dict)  # overrides of the LLM_* settings
    vendor_caps: dict[str, int] = field(default_factory=dict)  # micro-USD a month, per vendor

    def plan(self, code: str) -> Plan:
        """The plan with this code; the default plan if it was removed from the catalog."""
        if code == UNLIMITED.code:
            return UNLIMITED
        return self.plans.get(code) or self.plans.get(self.default_plan) or FREE


def plan_to_json(plan: Plan) -> dict[str, Any]:
    return {
        "code": plan.code,
        "name": plan.name,
        "limits": {step.value: plan.limits.get(step) for step in UsageStep if step in plan.limits},
        "seats": plan.seats,
        "mailboxes": plan.mailboxes,
        "active_campaigns": plan.active_campaigns,
        "max_leads_per_run": plan.max_leads_per_run,
        "max_prospect_budget_micro_usd": plan.max_prospect_budget_micro_usd,
        "features": sorted(plan.features),
        "access_days": plan.access_days,
    }


def plan_from_json(data: dict[str, Any]) -> Plan:
    known = {step.value: step for step in UsageStep}
    limits = {
        known[name]: (None if value is None else int(value))
        for name, value in (data.get("limits") or {}).items()
        if name in known
    }
    base = FREE

    def number(key: str, default: int | None) -> int | None:
        return int(data[key]) if data.get(key) is not None else (None if key in data else default)

    return Plan(
        code=str(data["code"]),
        name=str(data.get("name") or data["code"]),
        limits=limits,
        seats=number("seats", base.seats),
        mailboxes=number("mailboxes", base.mailboxes),
        active_campaigns=number("active_campaigns", base.active_campaigns),
        max_leads_per_run=number("max_leads_per_run", base.max_leads_per_run),
        max_prospect_budget_micro_usd=number(
            "max_prospect_budget_micro_usd", base.max_prospect_budget_micro_usd
        ),
        features=frozenset(str(f) for f in data.get("features", base.features)),
        access_days=number("access_days", base.access_days),
    )


def to_json(settings: PlatformSettings) -> dict[str, Any]:
    return {
        "plans": [plan_to_json(p) for p in settings.plans.values()],
        "default_plan": settings.default_plan,
        "kill_runs": settings.kill_runs,
        "kill_drafts": settings.kill_drafts,
        "superadmin_enabled": settings.superadmin_enabled,
        "announcement": settings.announcement,
        "paused_vendors": sorted(settings.paused_vendors),
        "llm": settings.llm,
        "vendor_caps": settings.vendor_caps,
    }


def from_json(data: dict[str, Any]) -> PlatformSettings:
    defaults = PlatformSettings()
    plans = {p.code: p for p in (plan_from_json(d) for d in data.get("plans", []) if "code" in d)}
    return PlatformSettings(
        plans=plans or defaults.plans,
        default_plan=str(data.get("default_plan") or defaults.default_plan),
        kill_runs=bool(data.get("kill_runs", False)),
        kill_drafts=bool(data.get("kill_drafts", False)),
        superadmin_enabled=bool(data.get("superadmin_enabled", True)),
        announcement=str(data.get("announcement") or ""),
        paused_vendors=frozenset(str(v) for v in data.get("paused_vendors", [])),
        llm={str(k): v for k, v in (data.get("llm") or {}).items() if k in LLM_FIELDS},
        vendor_caps={str(k): int(v) for k, v in (data.get("vendor_caps") or {}).items()},
    )
