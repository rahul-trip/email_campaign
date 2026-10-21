"""Lifecycles as transition tables. A move that is not in the table cannot be written.

Repositories call ``check`` before every status change and write an ``events`` row in the same
transaction, so no caller can skip a rule or leave a change unlogged.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from outbound.domain.enums import (
    CompanyStatus,
    ContactStatus,
    EmailStatus,
    HoldReason,
    MessageState,
    RunStatus,
)


class IllegalTransition(Exception):
    def __init__(self, machine: str, current: StrEnum, target: StrEnum) -> None:
        super().__init__(f"{machine}: cannot move from {current.value!r} to {target.value!r}")
        self.machine = machine
        self.current = current
        self.target = target


class StateMachine[S: StrEnum]:
    def __init__(self, name: str, table: Mapping[S, frozenset[S]], states: type[S]) -> None:
        missing = [state for state in states if state not in table]
        if missing:
            raise ValueError(f"{name}: no row in the table for {[m.value for m in missing]}")
        self.name = name
        self._table = dict(table)

    def targets(self, current: S) -> frozenset[S]:
        return self._table[current]

    def allows(self, current: S, target: S) -> bool:
        return target in self._table[current]

    def check(self, current: S, target: S) -> None:
        if not self.allows(current, target):
            raise IllegalTransition(self.name, current, target)

    def is_final(self, current: S) -> bool:
        return not self._table[current]


def _row[S: StrEnum](*targets: S) -> frozenset[S]:
    return frozenset(targets)


C = CompanyStatus

# The stages that can fail a lead, with their input status: a retry resumes there. Deliver and
# sync never fail a lead; they leave it where it is and try again later.
STAGE_INPUT_STATUS: Mapping[str, CompanyStatus] = {
    "research": C.NEW,
    "gate": C.RESEARCHED,
    "contacts": C.QUALIFIED,
    "email": C.CONTACTS_FOUND,
    "copy": C.EMAIL_READY,
}

COMPANY = StateMachine(
    "company",
    {
        C.NEW: _row(C.RESEARCHED, C.FAILED, C.SUPPRESSED),
        C.RESEARCHED: _row(C.QUALIFIED, C.DISQUALIFIED, C.HELD, C.FAILED, C.SUPPRESSED),
        C.QUALIFIED: _row(C.CONTACTS_FOUND, C.HELD, C.FAILED, C.SUPPRESSED),
        # An operator can override a low fit score.
        C.DISQUALIFIED: _row(C.QUALIFIED, C.SUPPRESSED),
        C.CONTACTS_FOUND: _row(C.EMAIL_READY, C.HELD, C.FAILED, C.SUPPRESSED),
        # Back to CONTACTS_FOUND when the operator picks a different person to write to.
        C.EMAIL_READY: _row(C.COPY_READY, C.CONTACTS_FOUND, C.HELD, C.FAILED, C.SUPPRESSED),
        # Released back to where the hold came from; see ``resume_status_for``.
        C.HELD: _row(C.RESEARCHED, C.CONTACTS_FOUND, C.REJECTED, C.FAILED, C.SUPPRESSED),
        C.COPY_READY: _row(C.APPROVED, C.CONTACTS_FOUND, C.REJECTED, C.SUPPRESSED),
        C.APPROVED: _row(C.IN_SEQUENCE, C.CONTACTS_FOUND, C.HELD, C.REJECTED, C.SUPPRESSED),
        # A bounce or a referral sends the lead back for the next contact.
        C.IN_SEQUENCE: _row(C.REPLIED, C.COMPLETED, C.CONTACTS_FOUND, C.SUPPRESSED),
        # A retry restores the input status of the stage that failed.
        C.FAILED: _row(
            C.NEW,
            C.RESEARCHED,
            C.QUALIFIED,
            C.CONTACTS_FOUND,
            C.EMAIL_READY,
            C.REJECTED,
            C.SUPPRESSED,
        ),
        C.REPLIED: _row(),
        C.COMPLETED: _row(),
        C.REJECTED: _row(),
        C.SUPPRESSED: _row(),
    },
    CompanyStatus,
)

_HELD_RESUMES: Mapping[HoldReason, CompanyStatus | None] = {
    HoldReason.CATCH_ALL_RESOLVING: C.CONTACTS_FOUND,
    HoldReason.CATCH_ALL_UNVERIFIED: C.CONTACTS_FOUND,
    HoldReason.CONSENT_REQUIRED: C.RESEARCHED,
    HoldReason.COUNTRY_UNKNOWN: C.RESEARCHED,
    HoldReason.ENTITY_UNKNOWN: C.RESEARCHED,
    HoldReason.NEEDS_OPERATOR: None,  # the caller must choose where to resume
}


def resume_status_for(reason: HoldReason) -> CompanyStatus | None:
    """Where a held company goes when released: the stage that held it runs again."""
    return _HELD_RESUMES[reason]


def retry_status_for(failed_stage: str) -> CompanyStatus:
    return STAGE_INPUT_STATUS[failed_stage]


M = MessageState
MESSAGE = StateMachine(
    "message",
    {
        M.GENERATED: _row(M.APPROVED, M.REJECTED, M.CANCELLED),
        M.APPROVED: _row(M.DRAFTED, M.SENT, M.CANCELLED),
        M.DRAFTED: _row(M.SENT, M.CANCELLED),
        M.SENT: _row(M.BOUNCED),
        M.BOUNCED: _row(),
        M.REJECTED: _row(),
        M.CANCELLED: _row(),
    },
    MessageState,
)

E = EmailStatus
EMAIL = StateMachine(
    "email",
    {
        E.UNVERIFIED: _row(
            E.VALID,
            E.INVALID,
            E.UNKNOWN,
            E.CATCH_ALL_PENDING,
            E.CATCH_ALL_RESOLVED,
            E.CATCH_ALL_UNVERIFIED,
        ),
        E.UNKNOWN: _row(
            E.VALID,
            E.INVALID,
            E.CATCH_ALL_PENDING,
            E.CATCH_ALL_RESOLVED,
            E.CATCH_ALL_UNVERIFIED,
        ),
        E.CATCH_ALL_PENDING: _row(E.CATCH_ALL_RESOLVED, E.CATCH_ALL_UNVERIFIED, E.INVALID),
        E.CATCH_ALL_UNVERIFIED: _row(E.CATCH_ALL_RESOLVED, E.INVALID),
        # A hard bounce can prove an address that looked fine was not.
        E.VALID: _row(E.INVALID),
        E.CATCH_ALL_RESOLVED: _row(E.INVALID),
        E.INVALID: _row(),  # never retried
    },
    EmailStatus,
)

R = RunStatus
RUN = StateMachine(
    "run",
    {
        R.QUEUED: _row(R.RUNNING, R.CANCELLED),
        R.RUNNING: _row(R.SUCCEEDED, R.FAILED, R.CANCELLED),
        R.SUCCEEDED: _row(),
        R.FAILED: _row(),
        R.CANCELLED: _row(),
    },
    RunStatus,
)

K = ContactStatus
CONTACT = StateMachine(
    "contact",
    {
        K.CANDIDATE: _row(K.ACTIVE, K.BOUNCED, K.REFERRED_AWAY, K.OPTED_OUT, K.FORGOTTEN),
        K.ACTIVE: _row(K.BOUNCED, K.REFERRED_AWAY, K.OPTED_OUT, K.FORGOTTEN),
        K.BOUNCED: _row(K.OPTED_OUT, K.FORGOTTEN),
        K.REFERRED_AWAY: _row(K.OPTED_OUT, K.FORGOTTEN),
        K.OPTED_OUT: _row(K.FORGOTTEN),
        K.FORGOTTEN: _row(),
    },
    ContactStatus,
)
