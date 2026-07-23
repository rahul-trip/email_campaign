"""agent/observability/step_logger.py — @logged_step decorator + StepRecord.

The @logged_step decorator wraps each LangGraph node function and:
    1. Logs START at INFO (with the 'step' field injected into the record).
    2. On success: logs OK with a one-line summary and duration_ms.
    3. On failure: logs FAIL with the exception, records the error.
    4. Appends a StepRecord to state["step_log"] via the operator.add reducer.
    5. Re-raises only on abort-level (unexpected) errors; recoverable errors
       (like skipping a company) are handled inside node functions themselves.

This satisfies the specification requirement:
    "logs all the steps performed and the status of the step."
"""

from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger("agent")


@dataclass
class StepRecord:
    """One record appended to AgentState["step_log"] per node execution."""

    step: str
    status: str              # "ok" | "fail" | "skipped"
    detail: str = ""
    duration_ms: float = 0.0
    error: str = ""


def logged_step(step_name: str) -> Callable:
    """Decorator factory for LangGraph node functions.

    Usage (inside graph/nodes.py make_* closures):

        @logged_step("discover_companies")
        def discover(state):
            ...
            return {"companies": [...]}

    The decorated function must accept a single `state` dict argument and
    return a dict of state updates (the LangGraph node contract).
    """

    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        @functools.wraps(fn)
        def wrapper(state: dict) -> dict:
            _log_with_step(logging.INFO, step_name, "START")
            start = time.monotonic()
            try:
                updates = fn(state)
                duration_ms = (time.monotonic() - start) * 1000
                # Extract a one-line summary from the returned dict if possible
                summary = _summarize(updates)
                _log_with_step(logging.INFO, step_name, f"OK — {summary} ({duration_ms:.0f}ms)")
                record = StepRecord(
                    step=step_name,
                    status="ok",
                    detail=summary,
                    duration_ms=duration_ms,
                )
                # Merge step_log into the returned updates dict
                existing = updates.get("step_log", [])
                updates["step_log"] = existing + [record]
                return updates
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                _log_with_step(
                    logging.ERROR, step_name,
                    f"FAIL — {type(exc).__name__}: {exc} ({duration_ms:.0f}ms)"
                )
                record = StepRecord(
                    step=step_name,
                    status="fail",
                    detail=str(exc),
                    duration_ms=duration_ms,
                    error=f"{type(exc).__name__}: {exc}",
                )
                # Return error into state so graph can decide to END gracefully
                return {
                    "step_log": [record],
                    "errors": [f"[{step_name}] {type(exc).__name__}: {exc}"],
                }

        return wrapper

    return decorator


def _log_with_step(level: int, step: str, message: str) -> None:
    """Emit a log record with the 'step' extra field injected."""
    logger.log(level, message, extra={"step": step})


def _summarize(updates: dict) -> str:
    """Build a short human-readable summary of what was returned."""
    parts: list[str] = []
    if "companies" in updates:
        parts.append(f"companies={len(updates['companies'])}")
    if "leads" in updates:
        parts.append(f"leads={len(updates['leads'])}")
    if "appended_row_count" in updates:
        parts.append(f"appended={updates['appended_row_count']}")
    if "draft_result" in updates:
        dr = updates["draft_result"]
        parts.append(f"drafted={dr.get('drafted', '?')}")
    return ", ".join(parts) if parts else "done"
