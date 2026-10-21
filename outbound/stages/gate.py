"""Stage 3: is this company worth contacting, and may we contact it at all?

Two checks, in order. The fit gate compares the research score with the campaign minimum
(a lead the operator chose by hand skips it, but keeps its score). The country policy then
decides whether the lead is allowed, blocked or must wait for a person. The decision, with the
policy version it used, is stored on the company for later audit.
"""

from __future__ import annotations

from outbound.domain.enums import CompanyStatus
from outbound.domain.policies import PolicyOutcome, passes_fit_gate
from outbound.stages.base import StageContext, StageResult
from outbound.stages.policy import policy_decision_for

DEFAULT_MIN_FIT_SCORE = 60


class GateStage:
    name = "gate"
    input_status = CompanyStatus.RESEARCHED
    guard_policy = False  # this stage makes the policy decision itself
    spends = False

    def handle(self, ctx: StageContext) -> StageResult:
        company = ctx.company
        minimum = ctx.campaign.min_fit_score if ctx.campaign else DEFAULT_MIN_FIT_SCORE

        if not passes_fit_gate(
            source=company.source, fit_score=company.fit_score, min_fit_score=minimum
        ):
            score = "no score" if company.fit_score is None else f"score {company.fit_score}"
            return StageResult(
                CompanyStatus.DISQUALIFIED, reason=f"fit: {score}, the campaign needs {minimum}"
            )

        decision = ctx.read(lambda uow: policy_decision_for(uow, company, stage=self.name))
        recorded = {"policy_decision": decision.to_json()}
        reason = "; ".join(decision.reasons) or "allowed"

        if decision.outcome is PolicyOutcome.ALLOW:
            return StageResult(CompanyStatus.QUALIFIED, reason=reason, company_updates=recorded)
        if decision.outcome is PolicyOutcome.BLOCK:
            return StageResult(CompanyStatus.DISQUALIFIED, reason=reason, company_updates=recorded)
        return StageResult(
            CompanyStatus.HELD,
            reason=reason,
            hold_reason=decision.hold_reason,
            company_updates=recorded,
        )
