from __future__ import annotations

import pytest

from outbound.domain.enums import CompanyStatus as S
from outbound.domain.enums import FailureKind as K
from outbound.domain.enums import HoldReason
from outbound.domain.outcomes import ERROR_TRIES, OUTCOME_TRIES, Bucket, bucket_of, tries_allowed


def test_an_email_waiting_for_approval_is_ready() -> None:
    assert bucket_of(S.COPY_READY) is Bucket.READY


def test_the_steps_before_an_email_are_working() -> None:
    for status in (S.NEW, S.RESEARCHED, S.QUALIFIED, S.CONTACTS_FOUND, S.EMAIL_READY):
        assert bucket_of(status) is Bucket.WORKING


def test_a_lead_that_does_not_fit_is_screened_out_not_failed() -> None:
    for status in (S.DISQUALIFIED, S.REJECTED, S.SUPPRESSED):
        assert bucket_of(status) is Bucket.SCREENED_OUT


def test_a_hold_waits_for_a_person_unless_a_resolver_is_on_it() -> None:
    assert bucket_of(S.HELD, hold_reason=HoldReason.CONSENT_REQUIRED) is Bucket.DECISION
    assert bucket_of(S.HELD, hold_reason=HoldReason.CATCH_ALL_RESOLVING) is Bucket.WORKING


@pytest.mark.parametrize("kind", [K.NO_PERSON, K.NO_EMAIL])
def test_nobody_to_write_to_is_working_until_the_tries_run_out_then_screened_out(kind: K) -> None:
    assert bucket_of(S.FAILED, failure_kind=kind, attempts=1) is Bucket.WORKING
    assert bucket_of(S.FAILED, failure_kind=kind, attempts=OUTCOME_TRIES) is Bucket.SCREENED_OUT


def test_a_hot_lead_nobody_could_email_is_ready_for_linkedin() -> None:
    def at(fit: int | None) -> Bucket:
        return bucket_of(S.FAILED, failure_kind=K.NO_EMAIL, attempts=OUTCOME_TRIES, fit_score=fit)

    assert at(81) is Bucket.READY
    assert at(80) is Bucket.SCREENED_OUT
    assert at(None) is Bucket.SCREENED_OUT


def test_a_broken_step_is_retried_and_only_then_asks_for_a_person() -> None:
    assert bucket_of(S.FAILED, failure_kind=K.ERROR, attempts=ERROR_TRIES - 1) is Bucket.WORKING
    assert bucket_of(S.FAILED, failure_kind=K.ERROR, attempts=ERROR_TRIES) is Bucket.DECISION
    assert bucket_of(S.FAILED, failure_kind=None, attempts=ERROR_TRIES) is Bucket.DECISION


def test_a_lead_waiting_for_credits_is_working_whatever_it_failed_at() -> None:
    assert bucket_of(S.FAILED, attempts=9, waiting_for_credit=True) is Bucket.WORKING


def test_approved_and_later_are_done() -> None:
    for status in (S.APPROVED, S.IN_SEQUENCE, S.REPLIED, S.COMPLETED):
        assert bucket_of(status) is Bucket.DONE


def test_outcomes_get_fewer_tries_than_breakages() -> None:
    assert tries_allowed(K.ERROR) == ERROR_TRIES == 5
    assert tries_allowed(K.NO_EMAIL) == tries_allowed(K.NO_PERSON) == OUTCOME_TRIES == 3


@pytest.mark.parametrize("kind", [K.NO_PERSON, K.NO_EMAIL, K.ERROR])
def test_a_stopped_lead_with_a_linkedin_message_is_ready_not_failed(kind: K) -> None:
    """Someone there can be written to on LinkedIn, so it is a way in whatever stopped the email."""
    for fit in (None, 40, 95):
        assert (
            bucket_of(S.FAILED, failure_kind=kind, attempts=9, fit_score=fit, has_linkedin=True)
            is Bucket.READY
        )
    assert bucket_of(S.FAILED, failure_kind=kind, attempts=9, fit_score=40) is not Bucket.READY


def test_a_lead_waiting_for_credits_stays_working_even_with_a_linkedin_message() -> None:
    assert bucket_of(S.FAILED, waiting_for_credit=True, has_linkedin=True) is Bucket.WORKING
