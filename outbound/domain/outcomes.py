"""Where a lead stands, in the words an operator cares about. No I/O.

Most companies a campaign looks at are meant to drop out: they do not fit, nobody suitable works
there, or no address can be proven. Showing those as failures buries the few leads that matter,
so every lead belongs to exactly one bucket, and only one of them asks anything of a person.

* ``READY``: an email waits for approval, or a person at the lead can be written to on LinkedIn
  (a message is written for them), or a hot lead that cannot be emailed has no one yet.
* ``WORKING``: the engine is on it, or will try again by itself.
* ``DECISION``: only a person can unblock it (a hold, or a step that broke on every try).
* ``SCREENED_OUT``: a normal end: not a fit, rejected, suppressed, or nobody to write to.
* ``DONE``: approved and on its way, in a sequence, replied or completed.
"""

from __future__ import annotations

from enum import StrEnum

from outbound.domain.enums import CompanyStatus, FailureKind, HoldReason
from outbound.domain.qualification import is_hot

# How many times a lead is tried before the engine stops. A broken step is retried soon and more
# often; "nobody to write to" is an answer, so it is asked again only a few times, a day apart,
# in case people or addresses turn up.
ERROR_TRIES = 5
OUTCOME_TRIES = 3

# Holds that wait for the engine, not for a person.
SELF_RESOLVING_HOLDS = frozenset({HoldReason.CATCH_ALL_RESOLVING})

_DONE = frozenset(
    {
        CompanyStatus.APPROVED,
        CompanyStatus.IN_SEQUENCE,
        CompanyStatus.REPLIED,
        CompanyStatus.COMPLETED,
    }
)
_SCREENED = frozenset(
    {CompanyStatus.DISQUALIFIED, CompanyStatus.REJECTED, CompanyStatus.SUPPRESSED}
)


class Bucket(StrEnum):
    READY = "ready"
    WORKING = "working"
    DECISION = "decision"
    SCREENED_OUT = "screened_out"
    DONE = "done"


def tries_allowed(kind: FailureKind | None) -> int:
    """How many tries a failed lead gets before it stops."""
    return ERROR_TRIES if kind in (None, FailureKind.ERROR) else OUTCOME_TRIES


def gave_up_for_want_of_a_person(
    status: CompanyStatus, kind: FailureKind | None, attempts: int
) -> bool:
    """A lead that failed to find a person or an address on every try: a normal end."""
    return (
        status is CompanyStatus.FAILED
        and kind in (FailureKind.NO_PERSON, FailureKind.NO_EMAIL)
        and attempts >= tries_allowed(kind)
    )


def bucket_of(
    status: CompanyStatus,
    *,
    hold_reason: HoldReason | None = None,
    failure_kind: FailureKind | None = None,
    attempts: int = 0,
    fit_score: int | None = None,
    waiting_for_credit: bool = False,
    has_linkedin: bool = False,
) -> Bucket:
    """``has_linkedin``: a LinkedIn message is written (or sent) for someone at the lead. A lead
    that stopped for want of an address, or whose last step broke, still has a way in, so it is
    ready for a person to use, not a failure."""
    if status is CompanyStatus.COPY_READY:
        return Bucket.READY
    if status in _DONE:
        return Bucket.DONE
    if status in _SCREENED:
        return Bucket.SCREENED_OUT
    if status is CompanyStatus.HELD:
        return Bucket.WORKING if hold_reason in SELF_RESOLVING_HOLDS else Bucket.DECISION
    if status is CompanyStatus.FAILED:
        if waiting_for_credit:
            return Bucket.WORKING
        if has_linkedin:
            return Bucket.READY
        if gave_up_for_want_of_a_person(status, failure_kind, attempts):
            # A hot lead with nobody to email is still worth a LinkedIn message.
            return Bucket.READY if is_hot(fit_score) else Bucket.SCREENED_OUT
        if attempts >= tries_allowed(failure_kind):
            return Bucket.DECISION  # a step broke on every try: only a person can look
        return Bucket.WORKING
    return Bucket.WORKING  # everything between intake and a written email
