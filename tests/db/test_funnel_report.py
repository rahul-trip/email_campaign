"""The funnel report: from a company found to a draft in Review, and which vendors fail."""

from __future__ import annotations

from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.enums import (
    CallOutcome,
    CandidateVerdict,
    CompanySource,
    CompanyStatus,
    HoldReason,
)
from outbound.services.reports import ReportService, outcome


def _candidate(
    uow: UnitOfWork, campaign_id: str, name: str, verdict: CandidateVerdict, score: int | None
) -> None:
    uow.candidates.add(
        campaign_id=campaign_id, run_id=None, name=name, name_key=name.lower(),
        verdict=verdict, screen_score=score,
    )  # fmt: skip


def test_a_lead_is_described_by_where_it_is() -> None:
    assert outcome(CompanyStatus.NEW, None, None) == "waiting"
    assert outcome(CompanyStatus.FAILED, None, "contacts") == "failed:contacts"
    assert outcome(CompanyStatus.HELD, HoldReason.CATCH_ALL_UNVERIFIED, None) == (
        "held:catch_all_unverified"
    )
    assert outcome(CompanyStatus.COPY_READY, None, None) == "copy_ready"


def test_the_funnel_counts_what_discovery_named_what_became_leads_and_which_vendors_fail(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        campaign = uow.campaigns.create("grid", ["CTO"])
        for name, verdict, score in [
            ("A", CandidateVerdict.ACCEPTED, 80),
            ("B", CandidateVerdict.REJECTED, 30),
            ("C", CandidateVerdict.REJECTED, None),  # turned down on words, never judged
            ("D", CandidateVerdict.UNSCREENED, None),
        ]:
            _candidate(uow, campaign.id, name, verdict, score)
        won = uow.companies.create(
            domain="a.io", source=CompanySource.DISCOVERY, campaign_id=campaign.id
        )
        failed = uow.companies.create(
            domain="b.io", source=CompanySource.DISCOVERY, campaign_id=campaign.id
        )
        uow.companies.create(domain="c.io", source=CompanySource.MANUAL, campaign_id=campaign.id)
        uow.companies.transition(
            failed.id, CompanyStatus.FAILED, expected_version=failed.row_version,
            failed_stage="contacts",
        )  # fmt: skip
        for outcome_, provider in [
            (CallOutcome.MISS, "scrubby"), (CallOutcome.ERROR, "scrubby"),
            (CallOutcome.ERROR, "scrubby"), (CallOutcome.HIT, "tavily"),
            (CallOutcome.CACHE_HIT, "tavily"),  # never reached the vendor
        ]:  # fmt: skip
            uow.calls.record(provider=provider, operation="x", request_hash="h", outcome=outcome_)
        uow.commit()
        assert won.id

    report = ReportService(factory, ws).funnel(days=7)
    assert report.named == 4 and report.judged == 2
    assert report.judged_share == 0.5 and report.lead_share == 0.25
    assert report.verdicts[CandidateVerdict.UNSCREENED] == 1
    assert report.leads == 3
    assert report.outcomes == {"waiting": 2, "failed:contacts": 1}
    scrubby = next(v for v in report.vendors if v.provider == "scrubby")
    tavily = next(v for v in report.vendors if v.provider == "tavily")
    assert (scrubby.calls, scrubby.errors) == (3, 2) and round(scrubby.error_rate, 2) == 0.67
    assert (tavily.calls, tavily.errors) == (1, 0)


def test_an_empty_workspace_has_an_empty_funnel(factory: UnitOfWorkFactory, ws: str) -> None:
    report = ReportService(factory, ws).funnel()
    assert report.named == 0 and report.leads == 0 and report.vendors == []
    assert report.judged_share is None and report.lead_share is None
