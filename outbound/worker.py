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
from outbound.logging import get_logger
from outbound.pipeline import Pipeline, execute_run
from outbound.services.runs import RunRequest

log = get_logger(__name__)

Assemble = Callable[[str], Pipeline]  # workspace id -> a freshly assembled pipeline


class Task(StrEnum):
    RUN = "run"  # a run someone queued
    TICK = "tick"  # the periodic pass


@dataclass(frozen=True)
class Job:
    workspace_id: str
    task: Task


class Worker:
    def __init__(
        self,
        container: Container,
        assemble: Assemble,
        *,
        threads: int = 4,
        tick_every: timedelta | None = timedelta(minutes=15),
        stale_after: timedelta = timedelta(minutes=30),
        tick_limit: int = 50,
        periodic: Sequence[Callable[[], object]] = (),
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._container = container
        self._assemble = assemble
        self._threads = threads
        self._tick_every = tick_every
        self._stale_after = stale_after
        self._tick_limit = tick_limit
        self._periodic = list(periodic)  # platform-wide jobs, once per tick interval
        self._now = now
        self._last_served: dict[str, datetime] = {}
        self._last_tick: dict[str, datetime] = {}
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
        jobs = [Job(ws, Task.RUN) for ws in queued if ws not in self._busy]
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
            return self._tick(job.workspace_id)
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
            execute_run(
                pipeline,
                self._container,
                workspace_id,
                RunRequest.from_params(claimed.params),
                run_id=claimed.id,
            )
        except Exception as error:
            log.exception("run_failed", run_id=claimed.id, error_type=type(error).__name__)
            self._fail(workspace_id, claimed.id, error)

    def _tick(self, workspace_id: str) -> bool:
        try:
            self._assemble(workspace_id).tick.run(limit=self._tick_limit, skip_idle=True)
        except RunInProgress:
            log.info("tick_skipped", workspace_id=workspace_id, reason="a run is in progress")
        except Exception as error:  # one workspace's broken tick must not stop the others
            log.exception("tick_failed", workspace_id=workspace_id, error_type=type(error).__name__)
        return True

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
                time.sleep(poll_seconds)
