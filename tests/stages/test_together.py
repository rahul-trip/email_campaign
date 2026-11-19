"""Independent calls for one lead are made side by side, keep their order, and keep their scope."""

from __future__ import annotations

import threading
import time
from functools import partial

import pytest

from outbound.metering.metered import call_scope, current_scope
from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.stages.together import together, together_tolerant


def test_results_come_back_in_order_and_the_calls_overlap() -> None:
    started = threading.Barrier(3, timeout=5)  # all three must be running at once to pass

    def slow(n: int) -> int:
        started.wait()
        return n

    assert together([partial(slow, n) for n in (1, 2, 3)]) == [1, 2, 3]


def test_each_call_keeps_the_callers_scope() -> None:
    with call_scope(company_id="lead-1", run_id="run-1"):
        seen = together([lambda: current_scope().company_id, lambda: current_scope().run_id])
    assert seen == ["lead-1", "run-1"]


def test_a_failure_is_raised_after_the_other_calls_finish() -> None:
    done: list[str] = []

    def fine() -> str:
        time.sleep(0.05)
        done.append("fine")
        return "fine"

    def broken() -> str:
        raise ValueError("bug")

    with pytest.raises(ValueError):
        together([broken, fine])
    assert done == ["fine"]


def test_a_vendor_error_can_be_tolerated_but_a_budget_stop_never() -> None:
    def vendor() -> str:
        raise ProviderError("search", "down")

    def budget() -> str:
        raise BudgetExceeded("search", "cap")

    ok = together_tolerant([lambda: "a", vendor])
    assert ok[0] == "a" and isinstance(ok[1], ProviderError)
    with pytest.raises(BudgetExceeded):
        together_tolerant([lambda: "a", budget])
    with pytest.raises(ProviderError):
        together([lambda: "a", vendor])
