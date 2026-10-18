"""One scheduler pass, started from cron or a launchd timer; there is no daemon.

A tick retries failed leads that have attempts left, runs periodic jobs (the catch-all poll and
the Sent-folder sync, both added with their stages), and then runs the pipeline over whatever
is due. Everything is driven by status and ``next_action_at``, so two ticks never overlap in
effect even if the timer fires early.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import RunKind, RunStatus
from outbound.logging import get_logger
from outbound.metering.metered import call_scope
from outbound.runner.runner import Runner, RunReport

log = get_logger(__name__)


class Job(Protocol):
    """Periodic work that is not a stage: it acts on many leads or on the mailbox."""

    name: str

    def run(self) -> dict[str, int]:
        """Do one pass and return counts for the run report."""
        ...


@dataclass
class TickReport:
    retried: int = 0
    jobs: dict[str, dict[str, int]] = field(default_factory=dict)
    pipeline: RunReport | None = None


class Tick:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        runner: Runner,
        jobs: Sequence[Job] = (),
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._runner = runner
        self._jobs = tuple(jobs)

    def run(self, *, limit: int = 50) -> TickReport:
        report = TickReport(retried=self._runner.retry_failed(limit=limit))
        if self._jobs:
            report.jobs = self._run_jobs()
        report.pipeline = self._runner.run_pipeline(limit=limit)
        return report

    def _run_jobs(self) -> dict[str, dict[str, int]]:
        with self._uow(self._workspace_id) as uow:
            run_id = uow.runs.start(RunKind.SYNC, {"jobs": [job.name for job in self._jobs]})
            uow.commit()
        results: dict[str, dict[str, int]] = {}
        status = RunStatus.SUCCEEDED
        for job in self._jobs:
            try:
                with call_scope(run_id=run_id):
                    results[job.name] = job.run()
            except Exception:  # one broken job must not stop the others
                log.exception("job_failed", job=job.name)
                results[job.name] = {"failed": 1}
                status = RunStatus.FAILED
        with self._uow(self._workspace_id) as uow:
            uow.runs.finish(run_id, status, results)
            uow.commit()
        return results
