"""Independent calls made side by side, for one lead.

A lead's research asks the search several things that do not depend on each other (its news and
its market's news, two searches for people, a few batches of profile lookups). Asked one after
another they add up; asked together they cost the longest one. Each call runs in a copy of the
caller's context, so the ledger still attributes it to the right run and lead.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import cast

from outbound.providers.errors import BudgetExceeded, ProviderError

MAX_TOGETHER = 4  # a lead's calls in flight at most, so lead concurrency times this stays small


def _run[T](calls: Sequence[Callable[[], T]]) -> list[T | Exception]:
    if not calls:
        return []
    with ThreadPoolExecutor(
        max_workers=min(len(calls), MAX_TOGETHER), thread_name_prefix="together"
    ) as pool:
        futures = [pool.submit(contextvars.copy_context().run, call) for call in calls]
    outcomes: list[T | Exception] = []
    for future in futures:
        error = future.exception()
        if error is None:
            outcomes.append(future.result())
        elif isinstance(error, Exception):
            outcomes.append(error)
        else:
            raise error  # not ours to hold back (KeyboardInterrupt and the like)
    return outcomes


def together[T](calls: Sequence[Callable[[], T]]) -> list[T]:
    """The results of ``calls``, in order, run side by side.

    Every call finishes before this returns; the first failure, in order, is then raised.
    """
    results = _run(calls)
    for result in results:
        if isinstance(result, Exception):
            raise result
    return cast(list[T], results)


def together_tolerant[T](calls: Sequence[Callable[[], T]]) -> list[T | ProviderError]:
    """As ``together``, but a vendor's ``ProviderError`` (not ``BudgetExceeded``) is returned in
    place of its call's result, for the caller to skip as it would have when making the calls in
    turn. Any other failure, and a budget stop, is raised."""
    results = _run(calls)
    for result in results:
        if isinstance(result, Exception) and (
            not isinstance(result, ProviderError) or isinstance(result, BudgetExceeded)
        ):
            raise result
    return cast(list[T | ProviderError], results)
