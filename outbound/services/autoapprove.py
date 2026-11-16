"""Approving the emails to cold leads without a person (off unless the workspace switches it on).

A lead whose fit score is above 80 is hot: its email always waits in Review. Any other email is
approved here on the worker's tick, through the same ``ReviewService.approve`` a person uses, so
the do-not-contact check and both state machines apply, and the deliver step then saves it as a
draft in the mailbox. An email that relies on a check someone skipped is left alone: approving
that is where a person confirms the skip. Nothing is sent: that stays a person's act.
"""

from __future__ import annotations

from outbound.db.errors import ConcurrencyConflict
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import AUTO
from outbound.domain.qualification import is_hot
from outbound.logging import get_logger
from outbound.services.review import ReviewError, ReviewService

log = get_logger(__name__)

SETTING = "auto_approve_cold"


class AutoApprover:
    """A tick job: ``run`` approves what may be approved without a person."""

    name = "auto_approve"

    def __init__(
        self, uow_factory: UnitOfWorkFactory, workspace_id: str, review: ReviewService
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._review = review

    def run(self) -> dict[str, int]:
        counts = {"approved": 0, "left": 0}
        with self._uow(self._workspace_id) as uow:
            workspace = uow.workspace()
        if workspace is None or not workspace.settings.get(SETTING, False):
            return counts
        for item in self._review.queue(limit=200):
            score = item.company.fit_score
            if score is None or is_hot(score) or item.skips:
                counts["left"] += 1  # a hot lead, no score, or a skipped check: a person decides
                continue
            try:
                self._review.approve(
                    item.message.id,
                    expected_version=item.message.row_version,
                    acknowledge_skips=False,
                    actor=AUTO,
                )
            except (ReviewError, ConcurrencyConflict):
                log.warning("auto_approve_left", message_id=item.message.id)
                counts["left"] += 1
                continue
            counts["approved"] += 1
        if counts["approved"]:
            log.info("auto_approved", workspace_id=self._workspace_id, **counts)
        return counts
