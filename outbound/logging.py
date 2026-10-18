"""Structured JSON logs. Bind ``run_id``, ``workspace_id`` and ``company_id`` as they become known
and every later line in that context carries them."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level.upper(), force=True)
    # Request logging would print URLs, and some vendors put the API key in the query string.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("alembic.runtime.migration").setLevel(
        logging.WARNING
    )  # keep CLI output clean
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "outbound") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


bind = structlog.contextvars.bind_contextvars
unbind = structlog.contextvars.unbind_contextvars
clear = structlog.contextvars.clear_contextvars
