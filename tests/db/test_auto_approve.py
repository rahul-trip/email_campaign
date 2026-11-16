"""Cold leads' emails may be approved without a person; hot leads' never are."""

from __future__ import annotations

from outbound.db.models import CompanyRow, MessageRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import AUTO
from outbound.domain.enums import MessageState
from outbound.services.autoapprove import AutoApprover
from outbound.services.review import ReviewService
from tests.db.test_review_and_deliver import copy_ready


def waiting(factory: UnitOfWorkFactory, ws: str, domain: str, score: int | None) -> str:
    company_id, message_id = copy_ready(factory, ws, domain=domain)
    with factory(ws) as uow:
        uow.session.get(CompanyRow, company_id).fit_score = score  # type: ignore[union-attr]
        uow.commit()
    return message_id


def switch(factory: UnitOfWorkFactory, ws: str, on: bool) -> None:
    with factory(ws) as uow:
        workspace = uow.workspace()
        assert workspace is not None
        uow.own_workspace.set_settings({**workspace.settings, "auto_approve_cold": on})
        uow.commit()


def state(factory: UnitOfWorkFactory, ws: str, message_id: str) -> MessageState:
    with factory(ws) as uow:
        return uow.messages.get(message_id).state


def approver(factory: UnitOfWorkFactory, ws: str) -> AutoApprover:
    return AutoApprover(factory, ws, ReviewService(factory, ws))


def test_nothing_is_approved_unless_the_workspace_switches_it_on(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cold = waiting(factory, ws, "a.com", 60)
    assert approver(factory, ws).run() == {"approved": 0, "left": 0}
    assert state(factory, ws, cold) is MessageState.GENERATED


def test_a_cold_lead_is_approved_and_a_hot_one_or_one_without_a_score_waits(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    switch(factory, ws, True)
    cold = waiting(factory, ws, "cold.com", 70)
    edge = waiting(factory, ws, "edge.com", 80)  # 80 is still cold
    hot = waiting(factory, ws, "hot.com", 81)
    unscored = waiting(factory, ws, "none.com", None)
    assert approver(factory, ws).run() == {"approved": 2, "left": 2}
    assert state(factory, ws, cold) is MessageState.APPROVED
    assert state(factory, ws, edge) is MessageState.APPROVED
    assert state(factory, ws, hot) is MessageState.GENERATED
    assert state(factory, ws, unscored) is MessageState.GENERATED


def test_a_cold_email_the_linter_flagged_is_still_approved(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    switch(factory, ws, True)
    flagged = waiting(factory, ws, "flag.com", 65)
    with factory(ws) as uow:
        uow.session.get(MessageRow, flagged).lint_report = {"flagged": True}  # type: ignore[union-attr]
        uow.commit()
    approver(factory, ws).run()
    assert state(factory, ws, flagged) is MessageState.APPROVED


def test_the_approval_is_the_engines_and_says_so(factory: UnitOfWorkFactory, ws: str) -> None:
    switch(factory, ws, True)
    message_id = waiting(factory, ws, "a.com", 50)
    approver(factory, ws).run()
    history = ReviewService(factory, ws).show(message_id).history
    approval = next(h for h in history if h.actor == AUTO)
    assert approval.what == "Approved automatically (cold lead)"


def test_an_email_the_engine_approved_does_not_count_as_sent_unedited(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    switch(factory, ws, True)
    automatic = waiting(factory, ws, "auto.com", 50)
    switch(factory, ws, False)
    by_hand = waiting(factory, ws, "hand.com", 50)
    switch(factory, ws, True)
    # Only the first is approved by the engine: the second is hot-or-not, but we approve it by hand.
    with factory(ws) as uow:
        uow.session.get(MessageRow, by_hand).state = MessageState.GENERATED  # type: ignore[union-attr]
        uow.commit()
    review = ReviewService(factory, ws)
    review.approve(by_hand)
    AutoApprover(factory, ws, review).run()
    with factory(ws) as uow:
        for message_id in (automatic, by_hand):
            row = uow.session.get(MessageRow, message_id)
            assert row is not None
            row.state = MessageState.SENT
            row.edit_distance = 0.0
        uow.commit()
    with factory(ws) as uow:
        stats = uow.reports.touch_one()
    assert (stats.written, stats.sent, stats.unedited) == (2, 1, 1)
