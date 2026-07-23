"""agent/observability/logging_setup.py — Logging configuration for agent runs.

Sets up two handlers:
    1. StreamHandler (console) — always at INFO (DEBUG if AGENT_DEBUG=1)
    2. FileHandler — per-run log file at agent/logs/agent_run_<run_id>.log

A LoggerAdapter injects the current "step" name into every log record so the
format reads:  2026-07-19 12:00:00 INFO agent [discover_companies]: …
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent / "logs"
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(step)s]: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class _StepFilter(logging.Filter):
    """Injects a 'step' field into every LogRecord (default '-')."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not hasattr(record, "step"):
            record.step = "-"  # type: ignore[attr-defined]
        return True


def configure_logging(run_id: str) -> logging.Logger:
    """Configure the 'agent' logger for a single run.

    Args:
        run_id: Unique run identifier (used in the log file name).

    Returns:
        The configured 'agent' logger.
    """
    level = logging.DEBUG if os.getenv("AGENT_DEBUG") == "1" else logging.INFO
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    logger = logging.getLogger("agent")
    logger.setLevel(level)
    logger.handlers.clear()  # avoid duplicate handlers on re-runs in the same process

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    console.addFilter(_StepFilter())
    logger.addHandler(console)

    # File handler
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"agent_run_{run_id}.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # always verbose in file
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_StepFilter())
    logger.addHandler(file_handler)

    logger.info("Logging initialized — run_id=%s log=%s", run_id, log_path)
    return logger
