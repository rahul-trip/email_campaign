from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from outbound.api.deps import Services, require, services
from outbound.api.schemas import (
    CostOut,
    DiscoverySearchOut,
    QualityOut,
    RunCallOut,
    RunIn,
    RunLeadOut,
    RunOut,
    StatusOut,
)
from outbound.db.types import utcnow
from outbound.domain.errors import InvalidInput
from outbound.domain.permissions import Permission as P
from outbound.services.runs import RunRequest

router = APIRouter(prefix="/api", tags=["runs"])


@router.post(
    "/runs", response_model=RunOut, status_code=202, dependencies=[Depends(require(P.RUNS_WRITE))]
)
def start_run(body: RunIn, svc: Annotated[Services, Depends(services)]) -> RunOut:
    """Queue a run; the worker process picks it up. The API never runs the pipeline itself."""
    if body.skip_directory and not svc.quota.quota().entitlements.has("directory_bypass"):
        raise InvalidInput("your plan does not include skipping the shared directory")
    request = RunRequest(
        limit=body.limit,
        only=tuple(body.only),
        mode=body.mode,
        discover=body.discover,
        campaign=body.campaign,
        skip_directory=body.skip_directory,
    )
    return RunOut.model_validate(svc.runs.queue(request))


@router.get("/runs", response_model=list[RunOut], dependencies=[Depends(require(P.RUNS_READ))])
def recent_runs(svc: Annotated[Services, Depends(services)]) -> list[RunOut]:
    return [RunOut.model_validate(r) for r in svc.runs.recent()]


@router.get("/runs/{run_id}", response_model=RunOut, dependencies=[Depends(require(P.RUNS_READ))])
def run(run_id: str, svc: Annotated[Services, Depends(services)]) -> RunOut:
    return RunOut.model_validate(svc.runs.get(run_id))


@router.get(
    "/runs/{run_id}/leads",
    response_model=list[RunLeadOut],
    dependencies=[Depends(require(P.RUNS_READ))],
)
def run_leads(run_id: str, svc: Annotated[Services, Depends(services)]) -> list[RunLeadOut]:
    """Every lead the run moved, held, failed or deferred, each with its steps."""
    return [RunLeadOut.model_validate(lead) for lead in svc.runs.leads(run_id)]


@router.get(
    "/runs/{run_id}/calls",
    response_model=list[RunCallOut],
    dependencies=[Depends(require(P.RUNS_READ))],
)
def run_calls(run_id: str, svc: Annotated[Services, Depends(services)]) -> list[RunCallOut]:
    """What the run asked of each vendor and what it cost, costliest first."""
    return [RunCallOut.model_validate(c) for c in svc.runs.calls(run_id)]


@router.get(
    "/runs/{run_id}/searches",
    response_model=list[DiscoverySearchOut],
    dependencies=[Depends(require(P.RUNS_READ))],
)
def run_searches(
    run_id: str, svc: Annotated[Services, Depends(services)]
) -> list[DiscoverySearchOut]:
    """The searches a run made to find new companies, and what each found."""
    return [DiscoverySearchOut.model_validate(x) for x in svc.runs.searches(run_id)]


@router.post(
    "/runs/{run_id}/cancel", response_model=RunOut, dependencies=[Depends(require(P.RUNS_WRITE))]
)
def cancel(run_id: str, svc: Annotated[Services, Depends(services)]) -> RunOut:
    return RunOut.model_validate(svc.runs.cancel(run_id))


@router.get("/status", response_model=StatusOut, dependencies=[Depends(require(P.LEADS_READ))])
def status(svc: Annotated[Services, Depends(services)]) -> StatusOut:
    report = svc.reports.status()
    return StatusOut(
        by_status={s.value: n for s, n in report.by_status.items()},
        held={r.value: n for r, n in report.held.items()},
        waiting_for_review=report.waiting_for_review,
    )


@router.get(
    "/reports/quality", response_model=QualityOut, dependencies=[Depends(require(P.REPORTS_READ))]
)
def quality(svc: Annotated[Services, Depends(services)]) -> QualityOut:
    report = svc.reports.quality()
    return QualityOut(
        written=report.written,
        flagged=report.flagged,
        sent=report.sent,
        unedited=report.unedited,
        companies=report.companies,
        holds={r.value: n for r, n in report.holds.items()},
        unedited_share=report.unedited_share,
        flag_rate=report.flag_rate,
        catch_all_share=report.catch_all_share,
    )


@router.get(
    "/reports/cost", response_model=CostOut, dependencies=[Depends(require(P.REPORTS_READ))]
)
def cost(
    svc: Annotated[Services, Depends(services)], days: Annotated[int, Query(ge=1, le=365)] = 30
) -> CostOut:
    now = utcnow()
    report = svc.reports.cost(now - timedelta(days=days), now + timedelta(seconds=1))
    return CostOut(
        total=report.total,
        per_prospect=report.per_prospect,
        prospects=report.prospects,
        by_provider=report.by_provider,
        calls_by_provider=report.calls_by_provider,
        outcomes={o.value: n for o, n in report.outcomes.items()},
        paid_calls=report.paid_calls,
    )
