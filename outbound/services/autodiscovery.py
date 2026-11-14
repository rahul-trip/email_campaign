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
from outbound.domain.enums import CompanyStatus, RunKind, RunStatus, UsageStep
from outbound.logging import get_logger
from outbound.metering.quota import quota_in
from outbound.services.runs import RunMode, RunRequest, RunService

log = get_logger(__name__)

SETTING = "auto_discovery"  # a workspace setting; on unless switched off
INTERVAL = timedelta(hours=24)  # one search per campaign a day, however it ended
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


@dataclass(frozen=True)
class AutoDiscovery:
    uow_factory: UnitOfWorkFactory
    workspace_id: str
    runs: RunService
    now: Callable[[], datetime] = utcnow

    def queue_due(self) -> str | None:
        """Queue a discovery run for the first campaign that is due one; returns the run's id.
        One at a time: the next campaign gets its turn once this run has been queued a day."""
        moment = self.now()
        with self.uow_factory(self.workspace_id) as uow:
            workspace = uow.workspace()
            if workspace is None or not workspace.settings.get(SETTING, True):
                return None
            quota, _ = quota_in(uow, moment)
            if not quota.engine or not quota.has_credit(UsageStep.DISCOVERY):
                return None  # nothing could be added, so do not search
            campaigns = [c for c in uow.campaigns.all() if _describes_customer(c)]
            recent = uow.runs.recent(100, kinds=(RunKind.PIPELINE,), requested_only=True)
            if any(r.status in (RunStatus.QUEUED, RunStatus.RUNNING) for r in recent):
                return None  # a run is already on its way
            chosen: str | None = None
            for campaign in campaigns:
                last = max(
                    (
                        r.created_at
                        for r in recent
                        if r.params
                        and r.params.get("mode") in _SEARCHING
                        and r.params.get("campaign") == campaign.name
                    ),
                    default=None,
                )
                if last is not None and moment - last < INTERVAL:
                    continue
                if uow.companies.count_in(BEFORE_EMAIL, campaign.id) >= BACKLOG:
                    continue  # plenty waiting; finish those first
                chosen = campaign.name
                break
        if chosen is None:
            return None
        request = RunRequest(
            mode=RunMode.DISCOVERY, discover=COUNT, campaign=chosen, automatic=True
        )
        run = self.runs.queue(request)
        log.info("auto_discovery_queued", run_id=run.id, campaign=chosen)
        return run.id


def _describes_customer(campaign: Campaign) -> bool:
    """Discovery needs an ideal customer to search for; a campaign with none is left alone."""
    return bool((campaign.icp_description or "").strip() or campaign.icp_brief)
