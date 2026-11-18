"""Discovery that runs by itself for a campaign that says who it is after.

The worker's timer asks, for each workspace, whether a campaign is due a search for new companies.
If so it queues an ordinary discovery run (the same one a person starts on the Runs page), so the
run has its page, its candidates, its cancel button and its credit and spend limits. Nothing here
searches: this only decides, and queues.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Campaign
from outbound.domain.enums import (
    CampaignStatus,
    CompanyStatus,
    MessageState,
    RunKind,
    RunStatus,
)
from outbound.logging import get_logger
from outbound.metering.quota import quota_in
from outbound.services.runs import RunMode, RunRequest, RunService

log = get_logger(__name__)

SETTING = "auto_discovery"  # a workspace setting; on unless switched off
PER_DAY_SETTING = "auto_discovery_per_day"  # searches a day, 1 to 6
LIMIT_SETTING = "auto_discovery_review_limit"  # no search while Review holds this many drafts
PER_DAY = 4  # about every six hours
REVIEW_LIMIT = 50
COUNT = 10  # leads to add per search (capped by the workspace's discovery credits)
BACKLOG = 10  # no search while this many of the campaign's leads still wait for their emails
# Where a lead still has work to do before it has an email: the backlog a search would add to.
BEFORE_EMAIL = (
    CompanyStatus.NEW,
    CompanyStatus.RESEARCHED,
    CompanyStatus.QUALIFIED,
    CompanyStatus.CONTACTS_FOUND,
)
_SEARCHING = (RunMode.DISCOVERY.value, RunMode.MIXED.value)

# Why nothing is queued now. ``not_yet`` is only the wait between two searches.
OFF = "off"
NO_CAMPAIGN = "no_campaign"
NO_CREDITS = "no_credits"
RUN_IN_PROGRESS = "run_in_progress"
REVIEW_FULL = "review_full"
BACKLOG_FULL = "backlog"
NOT_YET = "not_yet"


def interval_for(per_day: int) -> timedelta:
    """The wait between two searches: a day divided by how many a day."""
    return timedelta(hours=24) / max(1, min(6, per_day))


@dataclass(frozen=True)
class DiscoveryState:
    """Whether the next search can be queued, and if not, why: what the Runs page says."""

    reason: str | None  # None: due now
    campaign: str | None
    last_search: datetime | None
    next_search: datetime | None
    per_day: int
    review_limit: int
    waiting_for_review: int


@dataclass(frozen=True)
class AutoDiscovery:
    uow_factory: UnitOfWorkFactory
    workspace_id: str
    runs: RunService
    now: Callable[[], datetime] = utcnow

    def state(self) -> DiscoveryState:
        """Everything ``queue_due`` weighs, in the order it weighs it."""
        moment = self.now()
        with self.uow_factory(self.workspace_id) as uow:
            workspace = uow.workspace()
            settings = workspace.settings if workspace else {}
            per_day = max(1, min(6, int(settings.get(PER_DAY_SETTING) or PER_DAY)))
            limit = max(1, int(settings.get(LIMIT_SETTING) or REVIEW_LIMIT))
            waiting = uow.messages.count_in_state(MessageState.GENERATED)
            campaign = next(
                (
                    c
                    for c in uow.campaigns.all()
                    if c.status is CampaignStatus.ACTIVE and _describes_customer(c)
                ),
                None,
            )
            recent = uow.runs.recent(100, kinds=(RunKind.PIPELINE,), requested_only=True)
            last = (
                max(
                    (
                        r.created_at
                        for r in recent
                        if r.params
                        and r.params.get("mode") in _SEARCHING
                        and r.params.get("campaign") == campaign.name
                    ),
                    default=None,
                )
                if campaign
                else None
            )
            next_search = last + interval_for(per_day) if last else None
            quota, _ = quota_in(uow, moment)
            backlog = uow.companies.count_in(BEFORE_EMAIL, campaign.id) if campaign else 0
            busy = any(r.status in (RunStatus.QUEUED, RunStatus.RUNNING) for r in recent)

            reason: str | None = None
            if workspace is None or not settings.get(SETTING, True):
                reason = OFF
            elif campaign is None:
                reason = NO_CAMPAIGN
            elif not quota.engine or not quota.has_credits():
                reason = NO_CREDITS  # nothing could be added, so do not search
            elif busy:
                reason = RUN_IN_PROGRESS
            elif waiting >= limit:
                reason = REVIEW_FULL  # enough drafts wait for you; no more until you work them
            elif next_search is not None and moment < next_search:
                reason = NOT_YET
            elif backlog >= BACKLOG:
                reason = BACKLOG_FULL  # plenty waiting; finish those first
        return DiscoveryState(
            reason,
            campaign.name if campaign else None,
            last,
            next_search,
            per_day,
            limit,
            waiting,
        )

    def queue_due(self) -> str | None:
        """Queue a discovery run for the active campaign if it is due one; returns the run's id."""
        state = self.state()
        if state.reason is not None or state.campaign is None:
            log.debug("auto_discovery_skipped", reason=state.reason)
            return None
        request = RunRequest(
            mode=RunMode.DISCOVERY, discover=COUNT, campaign=state.campaign, automatic=True
        )
        run = self.runs.queue(request)
        log.info("auto_discovery_queued", run_id=run.id, campaign=state.campaign)
        return run.id


def _describes_customer(campaign: Campaign) -> bool:
    """Discovery needs an ideal customer to search for; a campaign with none is left alone."""
    return bool((campaign.icp_description or "").strip() or campaign.icp_brief)
