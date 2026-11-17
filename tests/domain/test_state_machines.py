"""Every allowed move is stated here independently of the code's table, and every other
pair of states must be refused."""

from __future__ import annotations

from enum import StrEnum

import pytest

from outbound.domain.enums import (
    CompanyStatus,
    ContactStatus,
    EmailStatus,
    HoldReason,
    LinkedInState,
    MessageState,
)
from outbound.domain.state_machines import (
    COMPANY,
    CONTACT,
    EMAIL,
    LINKEDIN,
    MESSAGE,
    STAGE_INPUT_STATUS,
    IllegalTransition,
    StateMachine,
    resume_status_for,
    retry_status_for,
)

C, M, E, K = CompanyStatus, MessageState, EmailStatus, ContactStatus

EXPECTED_COMPANY: dict[CompanyStatus, set[CompanyStatus]] = {
    C.NEW: {C.RESEARCHED, C.FAILED, C.SUPPRESSED},
    C.RESEARCHED: {C.NEW, C.QUALIFIED, C.DISQUALIFIED, C.HELD, C.FAILED, C.SUPPRESSED},
    C.QUALIFIED: {C.NEW, C.CONTACTS_FOUND, C.HELD, C.FAILED, C.SUPPRESSED},
    C.DISQUALIFIED: {C.NEW, C.QUALIFIED, C.SUPPRESSED},
    C.CONTACTS_FOUND: {C.NEW, C.EMAIL_READY, C.HELD, C.FAILED, C.SUPPRESSED},
    C.EMAIL_READY: {C.NEW, C.COPY_READY, C.CONTACTS_FOUND, C.HELD, C.FAILED, C.SUPPRESSED},
    C.HELD: {
        C.NEW,
        C.RESEARCHED,
        C.QUALIFIED,
        C.CONTACTS_FOUND,
        C.EMAIL_READY,
        C.REJECTED,
        C.FAILED,
        C.SUPPRESSED,
    },
    C.COPY_READY: {C.NEW, C.APPROVED, C.CONTACTS_FOUND, C.HELD, C.REJECTED, C.SUPPRESSED},
    C.APPROVED: {C.NEW, C.IN_SEQUENCE, C.CONTACTS_FOUND, C.HELD, C.REJECTED, C.SUPPRESSED},
    C.IN_SEQUENCE: {C.REPLIED, C.COMPLETED, C.CONTACTS_FOUND, C.SUPPRESSED},
    C.FAILED: {
        C.NEW,
        C.RESEARCHED,
        C.QUALIFIED,
        C.CONTACTS_FOUND,
        C.EMAIL_READY,
        C.REJECTED,
        C.SUPPRESSED,
    },
    C.REPLIED: set(),
    C.COMPLETED: set(),
    C.REJECTED: set(),
    C.SUPPRESSED: set(),
}
EXPECTED_MESSAGE: dict[MessageState, set[MessageState]] = {
    M.GENERATED: {M.APPROVED, M.REJECTED, M.CANCELLED},
    M.APPROVED: {M.DRAFTED, M.SENT, M.CANCELLED},
    M.DRAFTED: {M.SENT, M.CANCELLED},
    M.SENT: {M.BOUNCED},
    M.BOUNCED: set(),
    M.REJECTED: set(),
    M.CANCELLED: set(),
}
EXPECTED_EMAIL: dict[EmailStatus, set[EmailStatus]] = {
    E.UNVERIFIED: {
        E.VALID,
        E.INVALID,
        E.UNKNOWN,
        E.CATCH_ALL_PENDING,
        E.CATCH_ALL_RESOLVED,
        E.CATCH_ALL_UNVERIFIED,
    },
    E.UNKNOWN: {
        E.VALID,
        E.INVALID,
        E.CATCH_ALL_PENDING,
        E.CATCH_ALL_RESOLVED,
        E.CATCH_ALL_UNVERIFIED,
    },
    E.CATCH_ALL_PENDING: {E.CATCH_ALL_RESOLVED, E.CATCH_ALL_UNVERIFIED, E.INVALID},
    E.CATCH_ALL_UNVERIFIED: {E.CATCH_ALL_RESOLVED, E.INVALID},
    E.VALID: {E.INVALID},
    E.CATCH_ALL_RESOLVED: {E.INVALID},
    E.INVALID: set(),
}
EXPECTED_CONTACT: dict[ContactStatus, set[ContactStatus]] = {
    K.UNCONFIRMED: {K.CANDIDATE, K.ACTIVE, K.NOT_HERE, K.OPTED_OUT, K.FORGOTTEN},
    K.NOT_HERE: {K.CANDIDATE, K.OPTED_OUT, K.FORGOTTEN},
    K.CANDIDATE: {K.ACTIVE, K.BOUNCED, K.REFERRED_AWAY, K.NOT_HERE, K.OPTED_OUT, K.FORGOTTEN},
    K.ACTIVE: {K.BOUNCED, K.REFERRED_AWAY, K.OPTED_OUT, K.FORGOTTEN},
    K.BOUNCED: {K.OPTED_OUT, K.FORGOTTEN},
    K.REFERRED_AWAY: {K.OPTED_OUT, K.FORGOTTEN},
    K.OPTED_OUT: {K.FORGOTTEN},
    K.FORGOTTEN: set(),
}

L = LinkedInState
EXPECTED_LINKEDIN: dict[LinkedInState, set[LinkedInState]] = {
    L.DRAFTED: {L.SENT, L.SKIPPED},
    L.SKIPPED: {L.DRAFTED},
    L.SENT: set(),  # final: what was sent stays sent
}

MACHINES: list[tuple[StateMachine, dict]] = [  # type: ignore[type-arg]
    (COMPANY, EXPECTED_COMPANY),
    (MESSAGE, EXPECTED_MESSAGE),
    (EMAIL, EXPECTED_EMAIL),
    (CONTACT, EXPECTED_CONTACT),
    (LINKEDIN, EXPECTED_LINKEDIN),
]


def all_pairs() -> list[tuple[StateMachine, StrEnum, StrEnum, bool]]:  # type: ignore[type-arg]
    return [
        (machine, current, target, target in expected[current])
        for machine, expected in MACHINES
        for current in expected
        for target in expected
    ]


@pytest.mark.parametrize(
    ("machine", "current", "target", "allowed"),
    all_pairs(),
    ids=lambda v: v.value if isinstance(v, StrEnum) else getattr(v, "name", str(v)),
)
def test_each_pair_of_states(machine, current, target, allowed) -> None:  # type: ignore[no-untyped-def]
    assert machine.allows(current, target) is allowed
    if allowed:
        machine.check(current, target)
    else:
        with pytest.raises(IllegalTransition, match=machine.name):
            machine.check(current, target)


def test_a_machine_must_describe_every_state() -> None:
    with pytest.raises(ValueError, match="no row"):
        StateMachine("bad", {C.NEW: frozenset()}, CompanyStatus)


def test_final_states_have_no_exit() -> None:
    finals = {C.REPLIED, C.COMPLETED, C.REJECTED, C.SUPPRESSED}
    assert {s for s in CompanyStatus if COMPANY.is_final(s)} == finals
    assert EMAIL.is_final(E.INVALID)
    assert CONTACT.is_final(K.FORGOTTEN)


@pytest.mark.parametrize("reason", [r for r in HoldReason if r is not HoldReason.NEEDS_OPERATOR])
def test_releasing_a_hold_resumes_where_it_started_and_is_a_legal_move(reason: HoldReason) -> None:
    target = resume_status_for(reason)
    assert target is not None
    COMPANY.check(C.HELD, target)


def test_a_hold_that_needs_an_operator_has_no_default_resume_point() -> None:
    assert resume_status_for(HoldReason.NEEDS_OPERATOR) is None


@pytest.mark.parametrize("stage", sorted(STAGE_INPUT_STATUS))
def test_retrying_a_failed_stage_is_a_legal_move_to_its_input_status(stage: str) -> None:
    target = retry_status_for(stage)
    COMPANY.check(C.FAILED, target)
    assert STAGE_INPUT_STATUS[stage] is target


def test_only_stages_that_can_fail_a_lead_have_a_retry_status() -> None:
    assert set(STAGE_INPUT_STATUS) == {"research", "gate", "contacts", "email", "copy"}
    for stage, status in STAGE_INPUT_STATUS.items():
        assert COMPANY.allows(status, C.FAILED), stage


def test_an_unverified_catch_all_cannot_skip_to_sendable_without_resolution() -> None:
    assert not EMAIL.allows(E.CATCH_ALL_UNVERIFIED, E.VALID)
    assert not EMAIL.allows(E.CATCH_ALL_PENDING, E.VALID)


def test_a_person_can_be_set_aside_as_not_here_and_confirmed_back() -> None:
    from outbound.domain.enums import ContactStatus as K
    from outbound.domain.state_machines import CONTACT

    for before in (K.UNCONFIRMED, K.CANDIDATE):
        assert CONTACT.allows(before, K.NOT_HERE)
    assert CONTACT.allows(K.NOT_HERE, K.CANDIDATE)
    assert not CONTACT.allows(K.NOT_HERE, K.ACTIVE)  # never straight to being written to
    assert not CONTACT.allows(K.ACTIVE, K.NOT_HERE)  # once active, suppress instead
