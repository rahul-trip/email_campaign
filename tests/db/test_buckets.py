"""The SQL filter and the counts agree with ``domain.outcomes.bucket_of``."""

from __future__ import annotations

from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    FailureKind,
    HoldReason,
    LinkedInState,
)
from outbound.domain.outcomes import Bucket, bucket_of

S = CompanyStatus
FORWARD = [S.RESEARCHED, S.QUALIFIED, S.CONTACTS_FOUND, S.EMAIL_READY]


def lead(uow: UnitOfWork, domain: str, *, fit: int | None = None) -> str:
    company = uow.companies.create(domain=domain, source=CompanySource.MANUAL)
    if fit is not None:
        uow.companies.update_fields(
            company.id, {"fit_score": fit}, actor=SYSTEM, expected_version=company.row_version
        )
    return company.id


def move(uow: UnitOfWork, company_id: str, *path: S, **kwargs: object) -> None:
    for to in path:
        current = uow.companies.get(company_id)
        extra = kwargs if to is path[-1] else {}
        uow.companies.transition(company_id, to, expected_version=current.row_version, **extra)  # type: ignore[arg-type]


def fail(uow: UnitOfWork, company_id: str, kind: FailureKind, times: int) -> None:
    for turn in range(times):
        move(uow, company_id, S.FAILED, failed_stage="research", last_error="x", failure_kind=kind)
        if turn < times - 1:
            move(uow, company_id, S.NEW)


def write_linkedin(uow: UnitOfWork, company_id: str, state: LinkedInState) -> None:
    contact = uow.contacts.add(company_id, rank=1, source=ContactSource.SITE)
    message = uow.linkedin.create(
        company_id=company_id, contact_id=contact.id, note="n", message="m", issues=[]
    )
    if state is not LinkedInState.DRAFTED:
        uow.linkedin.transition(message.id, state, actor=SYSTEM)


def test_every_bucket_filter_matches_the_domain_rule(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        lead(uow, "new.com")
        move(uow, lead(uow, "ready.com"), *FORWARD, S.COPY_READY)
        move(uow, lead(uow, "held.com"), *FORWARD, S.HELD, hold_reason=HoldReason.COUNTRY_UNKNOWN)
        move(
            uow,
            lead(uow, "resolving.com"),
            *FORWARD,
            S.HELD,
            hold_reason=HoldReason.CATCH_ALL_RESOLVING,
        )
        move(uow, lead(uow, "cold.com"), S.RESEARCHED, S.DISQUALIFIED)
        fail(uow, lead(uow, "retrying.com"), FailureKind.NO_EMAIL, 1)
        fail(uow, lead(uow, "gaveup.com", fit=50), FailureKind.NO_EMAIL, 3)
        fail(uow, lead(uow, "hotgaveup.com", fit=90), FailureKind.NO_PERSON, 3)
        fail(uow, lead(uow, "broken.com"), FailureKind.ERROR, 5)
        fail(uow, lead(uow, "flaky.com"), FailureKind.ERROR, 2)
        # A LinkedIn message for someone at the lead is a way in, whatever stopped the email.
        cold = lead(uow, "coldlinkedin.com", fit=40)
        fail(uow, cold, FailureKind.NO_EMAIL, 3)
        write_linkedin(uow, cold, LinkedInState.DRAFTED)
        stuck = lead(uow, "brokenlinkedin.com")
        fail(uow, stuck, FailureKind.ERROR, 5)
        write_linkedin(uow, stuck, LinkedInState.SENT)
        unused = lead(uow, "skippedlinkedin.com", fit=40)
        fail(uow, unused, FailureKind.NO_EMAIL, 3)
        write_linkedin(uow, unused, LinkedInState.SKIPPED)
        uow.commit()

        everyone = uow.companies.search(limit=200)[0]
        reachable = uow.companies.with_linkedin_messages([c.id for c in everyone])
        expected = {
            b: {c.domain for c in everyone if bucket_of_company(c, c.id in reachable) is b}
            for b in Bucket
        }
        for bucket in Bucket:
            found = {c.domain for c in uow.companies.search(bucket=bucket, limit=200)[0]}
            assert found == expected[bucket], bucket
        counts = uow.companies.count_buckets()
        assert counts == {b: len(expected[b]) for b in Bucket}
        assert expected[Bucket.READY] == {
            "ready.com",
            "hotgaveup.com",
            "coldlinkedin.com",
            "brokenlinkedin.com",
        }
        assert expected[Bucket.SCREENED_OUT] == {"cold.com", "gaveup.com", "skippedlinkedin.com"}
        assert expected[Bucket.DECISION] == {"held.com", "broken.com"}


def bucket_of_company(c: object, has_linkedin: bool = False) -> Bucket:
    return bucket_of(
        c.status,  # type: ignore[attr-defined]
        hold_reason=c.hold_reason,  # type: ignore[attr-defined]
        failure_kind=c.failure_kind,  # type: ignore[attr-defined]
        attempts=c.attempts,  # type: ignore[attr-defined]
        fit_score=c.fit_score,  # type: ignore[attr-defined]
        waiting_for_credit=c.credit_wait_step is not None,  # type: ignore[attr-defined]
        has_linkedin=has_linkedin,
    )
