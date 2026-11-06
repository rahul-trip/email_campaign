"""Companies discovery found and what it decided about each (``discovery_candidates``)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CandidateVerdict


def _campaign(factory: UnitOfWorkFactory, ws: str) -> str:
    with factory(ws) as uow:
        campaign = uow.campaigns.create("grid", ["CTO"])
        uow.commit()
    return campaign.id


def test_a_candidate_is_kept_with_its_sources_evidence_and_verdict(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = _campaign(factory, ws)
    with factory(ws) as uow:
        added = uow.candidates.add(
            campaign_id=cid,
            run_id="run-1",
            name="Gridcast",
            name_key="gridcast",
            domain="gridcast.io",
            sources=["yc_directory", "articles"],
            source_urls=["https://www.ycombinator.com/companies/gridcast"],
            description="Load forecasting for grid operators",
            evidence="Y Combinator Winter 2022",
            screen_score=82,
            rank_score=90,
            verdict=CandidateVerdict.REJECTED,
            reason="competitor",
        )
        uow.commit()
    with factory(ws) as uow:
        [found] = uow.candidates.for_run("run-1")
        assert found == added
        assert found.sources == ("yc_directory", "articles")
        assert uow.candidates.known_keys(cid) == {"gridcast"}
        assert uow.candidates.read_urls(cid) == {"https://www.ycombinator.com/companies/gridcast"}
        promoted = uow.candidates.decide(
            found.id, CandidateVerdict.ACCEPTED, reason="promoted", company_id="co-1"
        )
        uow.commit()
    assert (promoted.verdict, promoted.company_id) == (CandidateVerdict.ACCEPTED, "co-1")


def test_a_company_is_screened_once_per_campaign(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    cid = _campaign(factory, ws)
    fields: dict[str, Any] = {
        "run_id": None,
        "name": "Gridcast",
        "name_key": "gridcast",
        "verdict": CandidateVerdict.ACCEPTED,
    }
    with factory(ws) as uow:
        uow.candidates.add(campaign_id=cid, **fields)
        uow.commit()
    with factory(other_ws) as uow:
        assert uow.candidates.known_keys(cid) == set()  # another workspace sees nothing
    with factory(ws) as uow, pytest.raises(IntegrityError):
        uow.candidates.add(campaign_id=cid, **fields)


def test_fits_left_over_wait_for_the_next_run_best_first(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = _campaign(factory, ws)
    with factory(ws) as uow:
        for name, rank, verdict in (
            ("a", 60, CandidateVerdict.OVER_LIMIT),
            ("b", 90, CandidateVerdict.OVER_LIMIT),
            ("c", 99, CandidateVerdict.REJECTED),
        ):
            uow.candidates.add(
                campaign_id=cid, run_id=None, name=name, name_key=name, verdict=verdict,
                rank_score=rank,
            )  # fmt: skip
        uow.commit()
    with factory(ws) as uow:
        assert [c.name for c in uow.candidates.waiting(cid, 5)] == ["b", "a"]
        assert [c.name for c in uow.candidates.waiting(cid, 1)] == ["b"]
