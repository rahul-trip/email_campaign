"""Splits the suite across CI jobs. Off unless TEST_SHARD is set ("2/4": the second of four), so a
plain `pytest` runs everything, as always.

Whole files go to one shard, the slowest first to whichever has the least work so far, so a
file's own fixtures and order stay together and the shards finish at about the same time. A file's
seconds come from tests/shard_weights.json (measured with `pytest --durations=0`; refresh it when
the suite changes a lot); a file not listed counts as 0.02 s a test. Each shard runs on its own
runner with its own database.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    spec = os.environ.get("TEST_SHARD", "")
    if not spec:
        return
    index, total = (int(part) for part in spec.split("/"))
    counts = Counter(item.path for item in items)
    known = json.loads((Path(__file__).parent / "tests" / "shard_weights.json").read_text())
    root = Path(__file__).parent
    per_file = {
        path: known.get(path.relative_to(root).as_posix(), 0.02 * count)
        for path, count in counts.items()
    }
    load = [0.0] * total
    owner: dict[object, int] = {}
    for path, count in sorted(per_file.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        lightest = min(range(total), key=lambda i: (load[i], i))
        owner[path] = lightest
        load[lightest] += count
    mine = [item for item in items if owner[item.path] == index - 1]
    config.hook.pytest_deselected(items=[item for item in items if item not in mine])
    items[:] = mine
