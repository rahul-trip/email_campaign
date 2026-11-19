"""Splits the suite across CI jobs. Off unless TEST_SHARD is set ("2/4": the second of four), so a
plain `pytest` runs everything, as always.

Whole files go to one shard, the biggest first to whichever has the fewest tests so far, so a
file's own fixtures and order stay together and the shards finish at about the same time. Each
shard runs on its own runner with its own database.
"""

from __future__ import annotations

import os
from collections import Counter

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    spec = os.environ.get("TEST_SHARD", "")
    if not spec:
        return
    index, total = (int(part) for part in spec.split("/"))
    per_file = Counter(item.path for item in items)
    load = [0] * total
    owner: dict[object, int] = {}
    for path, count in sorted(per_file.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        lightest = min(range(total), key=lambda i: (load[i], i))
        owner[path] = lightest
        load[lightest] += count
    mine = [item for item in items if owner[item.path] == index - 1]
    config.hook.pytest_deselected(items=[item for item in items if item not in mine])
    items[:] = mine
