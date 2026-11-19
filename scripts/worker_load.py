"""A load check for the worker: many workspaces, fake vendors that take as long as real ones.

It builds a throwaway database with N workspaces, each with some leads, makes every vendor call
wait ``--delay-ms``, queues one run per workspace and lets the real ``Worker`` serve them. It
reports how long until the first draft appeared (per workspace), how long until every run was
done, and whether the 15-minute pass would have kept up. Run it once with the old behaviour and
once with the new, to see what the settings gain:

    uv run python -m scripts.worker_load                                   # the defaults
    uv run python -m scripts.worker_load --lead-concurrency 1 --no-flow --threads 4   # before
    uv run python -m scripts.worker_load --workspaces 15 --leads 20 --delay-ms 400

It uses SQLite by default, so it shows how the work is scheduled, not how fast Postgres is.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db import migrate
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.session import make_engine, make_session_factory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import EntityType, RunStatus
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.pipeline import Pipeline, assemble
from outbound.services.runs import RunRequest, RunService
from outbound.worker import Worker
from tests.db.conftest import make_workspace
from tests.stages.world import PROFILE, World


class Slow:
    """Wraps a fake vendor: every public method waits first, as a network call would."""

    def __init__(self, inner: Any, delay: float) -> None:
        self._inner, self._delay = inner, delay

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if not callable(attribute) or name.startswith("_"):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            time.sleep(self._delay)
            return attribute(*args, **kwargs)

        return call


def prepare(engine: Engine, name: str, leads: int) -> str:
    platform = PlatformUnitOfWorkFactory(make_session_factory(engine))
    factory = UnitOfWorkFactory(make_session_factory(engine))
    ws = make_workspace(platform, name)
    with factory(ws) as uow:
        workspace = uow.workspace()
        assert workspace is not None
        uow.own_workspace.set_sender_profile({**workspace.sender_profile, **PROFILE})
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        uow.campaigns.create(
            "default", ["CTO", "VP of Sales"], icp_description="Utilities that need forecasts"
        )
        uow.commit()
    rows = [
        {"Website": f"lead{n}-{name}.com", "Company": f"Lead {n} {name}", "Country": "US"}
        for n in range(leads)
    ]
    world = World()
    container = container_for(Settings(_env_file=None), engine)
    assemble(container, ws, world.providers()).intake.run(rows)
    return ws


def main() -> int:
    ask = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ask.add_argument("--workspaces", type=int, default=15)
    ask.add_argument("--leads", type=int, default=12, help="leads per workspace")
    ask.add_argument("--delay-ms", type=int, default=300, help="how long each vendor call takes")
    ask.add_argument("--threads", type=int, default=6, help="workspaces at once")
    ask.add_argument("--lead-concurrency", type=int, default=4)
    ask.add_argument("--no-flow", action="store_true", help="stage by stage, as before")
    ask.add_argument("--timeout", type=int, default=900, help="give up after this many seconds")
    args = ask.parse_args()

    folder = Path(tempfile.mkdtemp(prefix="outbound-load-"))
    url = f"sqlite:///{folder / 'load.db'}"
    migrate.upgrade(url)
    engine = make_engine(url)
    names = [f"w{n:02d}" for n in range(args.workspaces)]
    workspaces = [prepare(engine, name, args.leads) for name in names]
    container = container_for(Settings(_env_file=None), engine)
    delay = args.delay_ms / 1000

    def pipeline_for(workspace_id: str) -> Pipeline:
        world = World()
        providers = replace(
            world.providers(),
            search=Slow(world.search, delay),
            llm=Slow(world.llm, delay),
            finders=[Slow(world.finder, delay)],
            verifier=Slow(world.verifier, delay),
        )
        return assemble(
            container,
            workspace_id,
            providers,
            lead_concurrency=args.lead_concurrency,
            lead_flow=not args.no_flow,
        )

    for ws in workspaces:
        RunService(container.uow, ws).queue(RunRequest())
    worker = Worker(container, pipeline_for, threads=args.threads, tick_every=timedelta(minutes=15))
    done = threading.Event()
    started = time.monotonic()
    thread = threading.Thread(
        target=worker.run_forever, kwargs={"poll_seconds": 0.2, "stop": done.is_set}, daemon=True
    )
    thread.start()
    finished: dict[str, float] = {}
    while time.monotonic() - started < args.timeout and len(finished) < len(workspaces):
        for ws in workspaces:
            if ws not in finished:
                with container.uow(ws) as uow:
                    runs = uow.runs.recent(5)
                if runs and all(r.status in (RunStatus.SUCCEEDED, RunStatus.FAILED) for r in runs):
                    finished[ws] = time.monotonic() - started
        time.sleep(0.5)
    done.set()
    thread.join(timeout=30)

    first: list[float] = []
    for ws in workspaces:
        with container.uow(ws) as uow:
            drafts = [
                at
                for _, to, at in uow.events.status_changes_since(
                    EntityType.COMPANY, uow.runs.recent(1)[-1].created_at - timedelta(days=1)
                )
                if to == "copy_ready"
            ]
            began = min((r.created_at for r in uow.runs.recent(50)), default=None)
        if drafts and began:
            first.append((min(drafts) - began).total_seconds())
    print(f"{args.workspaces} workspaces x {args.leads} leads, vendor calls {args.delay_ms} ms")
    print(
        f"threads {args.threads}, leads in flight {args.lead_concurrency}, "
        f"{'stage by stage' if args.no_flow else 'lead by lead'}"
    )
    if first:
        print(
            f"first draft: median {statistics.median(first):.1f}s, slowest {max(first):.1f}s "
            f"({len(first)} of {len(workspaces)} workspaces)"
        )
    if finished:
        print(
            f"every run done: {max(finished.values()):.1f}s "
            f"({len(finished)} of {len(workspaces)} finished; "
            f"median {statistics.median(finished.values()):.1f}s)"
        )
    print(f"status: {worker.status()}")
    return 0 if len(finished) == len(workspaces) else 1


if __name__ == "__main__":
    raise SystemExit(main())
