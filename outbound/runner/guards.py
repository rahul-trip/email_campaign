"""Checks the runner makes before it hands a company to a stage.

They are the same for every stage, so no stage can forget them: suppression always wins, the
country policy is re-read (it may have changed since the gate), and a company that has used up
its budget gets no more paid work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from outbound.db.uow import UnitOfWork
from outbound.domain.entities import Company
from outbound.domain.enums import HoldReason
from outbound.domain.policies import PolicyOutcome
from outbound.metering.budget import BudgetPolicy
from outbound.stages.base import Stage
from outbound.stages.policy import policy_decision_for


class RefusalKind(StrEnum):
    SUPPRESSED = "suppressed"  # never contact: the domain is on the suppression list
    HOLD = "hold"  # wait for a person
    BUDGET = "budget"


@dataclass(frozen=True)
class Refusal:
    kind: RefusalKind
    reason: str
    hold_reason: HoldReason | None = None


class Guards:
    def __init__(self, budget: BudgetPolicy | None = None) -> None:
        self._budget = budget or BudgetPolicy()

    def check(self, uow: UnitOfWork, company: Company, stage: Stage) -> Refusal | None:
        if uow.suppressions.is_domain_suppressed(company.domain):
            return Refusal(RefusalKind.SUPPRESSED, f"{company.domain} is on the suppression list")

        if stage.guard_policy:
            decision = policy_decision_for(uow, company, stage=stage.name)
            # A country that blocks contact holds the lead rather than suppressing it: a rule
            # can come back into force (a skip revoked, the workspace switch turned back on),
            # and that must never end a lead for good. Only the suppression list does that.
            if decision.outcome is not PolicyOutcome.ALLOW:
                return Refusal(
                    RefusalKind.HOLD,
                    "; ".join(decision.reasons),
                    decision.hold_reason or HoldReason.NEEDS_OPERATOR,
                )

        ceiling = self._budget.per_prospect
        if ceiling is not None and stage.spends:
            spent = uow.calls.spend_on_company(company.id)
            if spent >= ceiling:
                return Refusal(
                    RefusalKind.BUDGET,
                    f"per-prospect budget used up ({spent} of {ceiling} micro-USD)",
                )
        return None
