"""The SQL filter and the counts agree with ``domain.outcomes.bucket_of``."""

from __future__ import annotations

from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.enums import CompanySource, CompanyStatus, FailureKind, HoldReason
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
        uow.commit()

        everyone = uow.companies.search(limit=200)[0]
        expected = {b: {c.domain for c in everyone if bucket_of_company(c) is b} for b in Bucket}
        for bucket in Bucket:
            found = {c.domain for c in uow.companies.search(bucket=bucket, limit=200)[0]}
            assert found == expected[bucket], bucket
        counts = uow.companies.count_buckets()
        assert counts == {b: len(expected[b]) for b in Bucket}
        assert expected[Bucket.READY] == {"ready.com", "hotgaveup.com"}
        assert expected[Bucket.SCREENED_OUT] == {"cold.com", "gaveup.com"}
        assert expected[Bucket.DECISION] == {"held.com", "broken.com"}


def bucket_of_company(c: object) -> Bucket:
    return bucket_of(
        c.status,  # type: ignore[attr-defined]
        hold_reason=c.hold_reason,  # type: ignore[attr-defined]
        failure_kind=c.failure_kind,  # type: ignore[attr-defined]
        attempts=c.attempts,  # type: ignore[attr-defined]
        fit_score=c.fit_score,  # type: ignore[attr-defined]
        waiting_for_credit=c.credit_wait_step is not None,  # type: ignore[attr-defined]
    )
