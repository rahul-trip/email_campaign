"""The worker: picks up runs queued by the API and executes them.

The API never runs the pipeline inside a request. It inserts a ``queued`` run; this process
claims it and calls the same code the CLI uses. One worker per workspace is enough for a single
operator, and a second would be safe (the claim skips rows another worker holds).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from outbound.bootstrap import Container
from outbound.domain.enums import RunStatus
from outbound.logging import get_logger
from outbound.pipeline import Pipeline, execute_run
from outbound.services.runs import RunRequest

log = get_logger(__name__)


class Worker:
    def __init__(self, container: Container, workspace_id: str, pipeline: Pipeline) -> None:
        self._container = container
        self._workspace_id = workspace_id
        self._pipeline = pipeline

    def run_once(self) -> bool:
        """Execute one queued run. Returns False when nothing was waiting."""
        with self._container.uow(self._workspace_id) as uow:
            claimed = uow.runs.claim_next()
            uow.commit()
        if claimed is None:
            return False
        log.info("run_claimed", run_id=claimed.id, params=claimed.params)
        try:
            execute_run(
                self._pipeline,
                self._container,
                self._workspace_id,
                RunRequest.from_params(claimed.params),
                run_id=claimed.id,
            )
        except Exception as error:
            log.exception("run_failed", run_id=claimed.id, error_type=type(error).__name__)
            self._fail(claimed.id, error)
        return True

    def run_forever(
        self, *, poll_seconds: float = 2.0, stop: Callable[[], bool] = lambda: False
    ) -> None:
        while not stop():
            try:
                worked = self.run_once()
            except Exception as error:  # a database hiccup must not end the worker for good
                log.exception("worker_error", error_type=type(error).__name__)
                worked = False
            if not worked:
                time.sleep(poll_seconds)

    def _fail(self, run_id: str, error: Exception) -> None:
        with self._container.uow(self._workspace_id) as uow:
            counts = {"error": f"{type(error).__name__}: {error}"[:300]}
            uow.runs.finish(run_id, RunStatus.FAILED, counts)
            uow.commit()
