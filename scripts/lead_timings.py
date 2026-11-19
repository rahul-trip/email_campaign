"""Where a lead's time goes: how long each step takes, and which vendor or model calls are slow.

Read-only. It reads the call ledger (every paid or cached call keeps its latency) and the status
history of every lead, for each workspace, and prints:

1. the slowest vendor and model operations (count, median, 95th percentile, total time);
2. how long leads spend in each status, from one status change to the next;
3. the first-draft time: from a lead's first appearance to its email waiting for review.

    uv run python -m scripts.lead_timings                 # the last 7 days, every workspace
    uv run python -m scripts.lead_timings --days 2
    uv run python -m scripts.lead_timings --workspace default

Use it before a change to the worker or the stages and again after, to see what it gained.
"""

from __future__ import annotations

import argparse
import itertools
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from outbound.bootstrap import build_container
from outbound.config import Settings
from outbound.db.types import utcnow
from outbound.domain.enums import EntityType


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))] if ordered else 0.0


def seconds(value: float) -> str:
    return f"{value:6.1f}s" if value < 600 else f"{value / 60:5.1f}min"


def stage_times(
    changes: list[tuple[str, str, datetime]],
) -> tuple[dict[str, list[float]], list[float]]:
    """Time spent before each status (the gap since the lead's previous change), and, per lead,
    the time from its first change to the email waiting for review (``copy_ready``)."""
    by_lead: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    for lead, status, at in changes:
        by_lead[lead].append((status, at))
    in_status: dict[str, list[float]] = defaultdict(list)
    first_draft: list[float] = []
    for steps in by_lead.values():
        for (_, before), (status, after) in itertools.pairwise(steps):
            in_status[status].append((after - before).total_seconds())
        start = steps[0][1]
        ready = next((at for status, at in steps if status == "copy_ready"), None)
        if ready is not None:
            first_draft.append((ready - start).total_seconds())
    return in_status, first_draft


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--workspace", help="one workspace by name (default: all)")
    args = parser.parse_args()

    container = build_container(Settings())
    since = utcnow() - timedelta(days=args.days)
    with container.platform() as platform:
        workspaces = [
            w for w in platform.workspaces.all() if not args.workspace or w.name == args.workspace
        ]
    calls: dict[tuple[str, str], list[float]] = defaultdict(list)
    changes: list[tuple[str, str, datetime]] = []
    for workspace in workspaces:
        with container.uow(workspace.id) as uow:
            for provider, operation, ms in uow.calls.latencies_since(since):
                calls[(provider, operation)].append(ms / 1000)
            changes += uow.events.status_changes_since(EntityType.COMPANY, since)
    print(f"Since {since:%Y-%m-%d %H:%M} UTC, {len(workspaces)} workspace(s)\n")

    print("Slowest calls (by total time)")
    print(f"{'vendor / operation':44} {'calls':>6} {'median':>8} {'p95':>8} {'total':>9}")
    ranked = sorted(calls.items(), key=lambda item: -sum(item[1]))
    for (provider, operation), values in ranked[:15]:
        label = f"{provider} / {operation}"
        print(
            f"{label:44.44} {len(values):6d} {seconds(statistics.median(values)):>8}"
            f" {seconds(percentile(values, 0.95)):>8} {seconds(sum(values)):>9}"
        )

    in_status, first_draft = stage_times(changes)
    print("\nTime before each status (the step that led to it, including waiting for a run)")
    print(f"{'status':20} {'leads':>6} {'median':>8} {'p95':>8}")
    for status, values in sorted(in_status.items(), key=lambda item: -statistics.median(item[1])):
        print(
            f"{status:20} {len(values):6d} {seconds(statistics.median(values)):>8}"
            f" {seconds(percentile(values, 0.95)):>8}"
        )
    if first_draft:
        print(
            f"\nFirst draft: {len(first_draft)} leads reached 'copy_ready'; from their first"
            f" change, median {seconds(statistics.median(first_draft)).strip()},"
            f" 95th percentile {seconds(percentile(first_draft, 0.95)).strip()}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
