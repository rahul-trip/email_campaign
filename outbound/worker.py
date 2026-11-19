"""The worker: executes queued runs and the periodic tick for every workspace.

The API never runs the pipeline inside a request. It inserts a ``queued`` run; this process
finds it, claims it and calls the same code the CLI uses. One worker serves every workspace:

- the platform unit of work answers only "which workspaces have work" (ids, no rows);
- claiming and executing happen in that workspace's own unit of work (its row-level security);
- a pipeline is assembled for each piece of work, because the runner keeps per-run state;
- each workspace has at most one piece of work in flight, the least recently served goes
  first, and a thread pool runs several workspaces side by side;
- every ``tick_every`` each active workspace gets a tick: retries, the catch-all poll, the Sent
  sync, and the pipeline if any lead is waiting;
- every ``due_check_every`` (a few minutes) each active workspace gets a light check: one cheap
  query, and the pipeline only if a lead is due, so work that appears between ticks (new leads,
  a lead whose wait is over, what a long batch left over) does not wait for the next tick; a pass
  that made progress is followed by another check at once;
- a run whose worker died (no heartbeat for ``stale_after``) is failed so it frees the queue.
"""

from __future__ import annotations

import contextvars
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from outbound.bootstrap import Container
from outbound.db.errors import RunInProgress
from outbound.db.repositories.audit import RunView
from outbound.db.types import utcnow
from outbound.domain.enums import RunStatus
from outbound.domain.state_machines import STAGE_INPUT_STATUS
from outbound.logging import get_logger
from outbound.pipeline import Pipeline, execute_run
from outbound.runner.runner import Outcome, RunReport
from outbound.services.activity_notices import ActivityNotifier
from outbound.services.autodiscovery import REVIEW_FULL, AutoDiscovery
from outbound.services.runs import RunRequest
from outbound.services.staff_alerts import StaffAlerts

log = get_logger(__name__)

Assemble = Callable[[str], Pipeline]  # workspace id -> a freshly assembled pipeline


class Task(StrEnum):
    RUN = "run"  # a run someone queued
    TICK = "tick"  # the periodic pass
    PIPELINE = "pipeline"  # the light check: run the pipeline if a lead is due


@dataclass(frozen=True)
class Job:
    workspace_id: str
    task: Task


def workspace_names(container: Container) -> Callable[[str], tuple[str, str] | None]:
    """A workspace's (slug, name) by id, for the notices the engine writes about it."""

    def find(workspace_id: str) -> tuple[str, str] | None:
        with container.platform() as platform:
            found = platform.workspaces.get(workspace_id)
        return (found.slug, found.name) if found else None

    return find


class Worker:
    def __init__(
        self,
        container: Container,
        assemble: Assemble,
        *,
        threads: int = 4,
        tick_every: timedelta | None = timedelta(minutes=15),
        due_check_every: timedelta | None = None,
        stale_after: timedelta = timedelta(minutes=30),
        tick_limit: int = 50,
        periodic: Sequence[Callable[[], object]] = (),
        now: Callable[[], datetime] = utcnow,
        notifier: ActivityNotifier | None = None,
        alerts: StaffAlerts | None = None,
    ) -> None:
        self._container = container
        self._assemble = assemble
        self._threads = threads
        self._tick_every = tick_every
        self._due_check_every = due_check_every  # None: only the tick starts unqueued work
        self._stale_after = stale_after
        self._tick_limit = tick_limit
        self._periodic = list(periodic)  # platform-wide jobs, once per tick interval
        self._notifier = notifier  # tells the workspace's people what a run or tick did
        self._alerts = alerts  # tells the platform's staff when something crashed
        self._now = now
        self._last_served: dict[str, datetime] = {}
        self._last_tick: dict[str, datetime] = {}
        self._last_due_check: dict[str, datetime] = {}
        self._busy: set[str] = set()

    # ------------------------------------------------------------------ planning

    def plan(self) -> list[Job]:
        """The work to start now: at most one job per workspace, not for a busy workspace,
        queued runs before ticks, the least recently served workspace first."""
        now = self._now()
        with self._container.platform() as platform:
            if platform.settings.get()[0].kill_runs:
                return []  # the platform's kill switch: nothing runs for anyone
            queued = platform.scheduler.with_queued_runs(now)
            active = platform.scheduler.active_workspaces(now) if self._tick_every else []
        # A workspace whose tick is more than a whole interval late gets the tick before its
        # queued run, so a workspace that always has a run waiting still has its mailboxes synced.
        late = (
            {ws for ws, at in self._last_tick.items() if at <= now - 2 * self._tick_every}
            if self._tick_every is not None
            else set()
        ) & set(active)
        jobs = [
            Job(ws, Task.TICK if ws in late else Task.RUN) for ws in queued if ws not in self._busy
        ]
        planned = {job.workspace_id for job in jobs}
        if self._tick_every is not None:
            due = self._now() - self._tick_every
            jobs += [
                Job(ws, Task.TICK)
                for ws in active
                if ws not in planned
                and ws not in self._busy
                and self._last_tick.get(ws, datetime.min.replace(tzinfo=due.tzinfo)) <= due
            ]
        never = datetime.min.replace(tzinfo=self._now().tzinfo)
        if self._due_check_every is not None and self._tick_every is not None:
            checked_before = self._now() - self._due_check_every
            planned = {job.workspace_id for job in jobs}
            jobs += [
                Job(ws, Task.PIPELINE)
                for ws in active
                if ws not in planned
                and ws not in self._busy
                and self._last_due_check.get(ws, never) <= checked_before
            ]
        return sorted(jobs, key=lambda job: self._last_served.get(job.workspace_id, never))

    def recover_stale(self) -> list[str]:
        """Fail running runs whose worker stopped; returns their ids."""
        cutoff = self._now() - self._stale_after
        with self._container.platform() as platform:
            workspaces = platform.scheduler.with_stale_runs(cutoff)
        failed: list[str] = []
        for workspace_id in workspaces:
            with self._container.uow(workspace_id) as uow:
                failed += uow.runs.fail_stale(cutoff)
                uow.commit()
        for run_id in failed:
            log.warning("run_stale_failed", run_id=run_id, stale_minutes=self._stale_after)
        return failed

    # ------------------------------------------------------------------ doing one job

    def execute(self, job: Job) -> bool:
        """Do one job in a clean context. Returns False when there turned out to be nothing."""
        return contextvars.Context().run(self._execute, job)

    def _execute(self, job: Job) -> bool:
        self._last_served[job.workspace_id] = self._now()
        if job.task is Task.TICK:
            self._last_tick[job.workspace_id] = self._now()
            self._last_due_check[job.workspace_id] = self._now()  # the tick looks at it too
            return self._tick(job.workspace_id)
        if job.task is Task.PIPELINE:
            self._last_due_check[job.workspace_id] = self._now()
            return self._pipeline_if_due(job.workspace_id)
        with self._container.uow(job.workspace_id) as uow:
            claimed = uow.runs.claim_next()
            uow.commit()
        if claimed is None:
            return False
        self._run(job.workspace_id, claimed)
        return True

    def _run(self, workspace_id: str, claimed: RunView) -> None:
        log.info("run_claimed", run_id=claimed.id, workspace_id=workspace_id, params=claimed.params)
        try:
            pipeline = self._assemble(workspace_id)
            request = RunRequest.from_params(claimed.params)
            report = execute_run(
                pipeline, self._container, workspace_id, request, run_id=claimed.id
            )
        except Exception as error:
            log.exception("run_failed", run_id=claimed.id, error_type=type(error).__name__)
            self._fail(workspace_id, claimed.id, error)
            self._alert("a run", error, f"Run {claimed.id}, workspace {workspace_id}.")
            reason = f"{type(error).__name__}: {error}"
            self._notify(workspace_id, lambda n: n.run_failed(workspace_id, claimed.id, reason))
        else:
            self._notify(
                workspace_id,
                lambda n: n.after_run(workspace_id, report.run_id, by_person=not request.automatic),
            )
            self._continue(workspace_id, report)

    def _tick(self, workspace_id: str) -> bool:
        try:
            pipeline = self._assemble(workspace_id)
            self._queue_discovery(workspace_id, pipeline)
            report = pipeline.tick.run(limit=self._tick_limit, skip_idle=True)
            self._notify(workspace_id, lambda n: n.after_tick(workspace_id, report))
            if report.pipeline is not None:
                self._continue(workspace_id, report.pipeline)
        except RunInProgress:
            log.info("tick_skipped", workspace_id=workspace_id, reason="a run is in progress")
        except Exception as error:  # one workspace's broken tick must not stop the others
            log.exception("tick_failed", workspace_id=workspace_id, error_type=type(error).__name__)
            self._alert("the 15-minute pass", error, f"Workspace {workspace_id}.")
        return True

    def _pipeline_if_due(self, workspace_id: str) -> bool:
        """The light check: one cheap query, and a pipeline run only if a lead is due."""
        with self._container.uow(workspace_id) as uow:
            due = uow.companies.any_due(list(STAGE_INPUT_STATUS.values()), self._now())
        if not due:
            return False
        try:
            pipeline = self._assemble(workspace_id)
            report = pipeline.runner.run_pipeline(limit=self._tick_limit)
            self._notify(
                workspace_id, lambda n: n.after_run(workspace_id, report.run_id, by_person=False)
            )
            self._continue(workspace_id, report)
        except RunInProgress:
            log.info("pipeline_skipped", workspace_id=workspace_id, reason="a run is in progress")
        except Exception as error:  # one workspace's broken pass must not stop the others
            log.exception(
                "pipeline_failed", workspace_id=workspace_id, error_type=type(error).__name__
            )
            self._alert("a pipeline pass", error, f"Workspace {workspace_id}.")
        return True

    def _continue(self, workspace_id: str, report: RunReport) -> None:
        """After a pass that moved leads, look again at once: a batch has a limit, so more may be
        waiting, and a lead that just advanced may be due at its next step. A pass that moved
        nothing waits for the usual interval, so a lead that cannot go on is not retried in a
        loop."""
        progress = {Outcome.ADVANCED, Outcome.HELD, Outcome.FAILED, Outcome.SUPPRESSED}
        moved = sum(
            n for c in report.counts.values() for o, n in c.items() if Outcome(o) in progress
        )
        if moved:
            self._last_due_check.pop(workspace_id, None)

    def _queue_discovery(self, workspace_id: str, pipeline: Pipeline) -> None:
        """Queue the search for new companies a campaign is due; the run is picked up next."""
        try:
            discovery = AutoDiscovery(self._container.uow, workspace_id, pipeline.runs, self._now)
            discovery.queue_due()
            state = discovery.state()
            if state.reason == REVIEW_FULL:
                self._notify(
                    workspace_id,
                    lambda n: n.discovery_paused(
                        workspace_id, state.waiting_for_review, state.review_limit
                    ),
                )
        except Exception as error:  # the tick's own work must still happen
            log.exception(
                "auto_discovery_failed", workspace_id=workspace_id, error_type=type(error).__name__
            )

    def _notify(self, workspace_id: str, tell: Callable[[ActivityNotifier], object]) -> None:
        """Tell the workspace's people what happened. Never allowed to fail a run or a tick."""
        if self._notifier is None:
            return
        try:
            tell(self._notifier)
        except Exception as error:
            log.exception(
                "notify_failed", workspace_id=workspace_id, error_type=type(error).__name__
            )

    def _alert(self, where: str, error: Exception, detail: str = "") -> None:
        if self._alerts is not None:
            self._alerts.error(where, error, detail=detail)

    def _fail(self, workspace_id: str, run_id: str, error: Exception) -> None:
        with self._container.uow(workspace_id) as uow:
            counts = {"error": f"{type(error).__name__}: {error}"[:300]}
            uow.runs.finish(run_id, RunStatus.FAILED, counts)
            uow.commit()

    # ------------------------------------------------------------------ loops

    def run_periodic(self) -> None:
        """Platform-wide jobs (notices). A failing one is logged and does not stop the others."""
        for job in self._periodic:
            try:
                job()
            except Exception as error:
                log.exception("periodic_failed", error_type=type(error).__name__)
                self._alert(
                    "a platform job", error, f"Job {getattr(job, '__qualname__', job)!s:.80}."
                )

    def run_once(self) -> bool:
        """One pass in this thread (tests, scripts): every planned job, one after another.
        Returns whether anything was done."""
        self.recover_stale()
        done = [self.execute(job) for job in self.plan()]  # every job, not just until one works
        return any(done)

    def run_forever(
        self, *, poll_seconds: float = 2.0, stop: Callable[[], bool] = lambda: False
    ) -> None:
        """Plan, hand jobs to the thread pool, and look again; until ``stop`` says so."""
        running: dict[Future[bool], str] = {}
        last_recovery = 0.0
        last_periodic = 0.0
        with ThreadPoolExecutor(max_workers=self._threads, thread_name_prefix="work") as pool:
            while not stop():
                for future in [f for f in running if f.done()]:
                    self._busy.discard(running.pop(future))
                try:
                    if time.monotonic() - last_recovery > 60:
                        self.recover_stale()
                        last_recovery = time.monotonic()
                    every = self._tick_every.total_seconds() if self._tick_every else None
                    if every and time.monotonic() - last_periodic > every:
                        last_periodic = time.monotonic()
                        self.run_periodic()
                    for job in self.plan()[: self._threads - len(running)]:
                        self._busy.add(job.workspace_id)
                        running[pool.submit(self.execute, job)] = job.workspace_id
                except Exception as error:  # a database hiccup must not end the worker
                    log.exception("worker_error", error_type=type(error).__name__)
                    self._alert("the worker", error)
                time.sleep(poll_seconds)
