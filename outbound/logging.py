"""Structured JSON logs. Bind ``run_id``, ``workspace_id`` and ``company_id`` as they become known
and every later line in that context carries them."""

from __future__ import annotations

import io
import logging
import sys
from typing import TextIO, cast

import structlog


class _CurrentStderr(io.TextIOBase):
    """A file-like that writes to whatever ``sys.stderr`` is at the moment of writing.

    structlog would otherwise keep the stream that existed when logging was configured. If that
    stream is later closed (a test runner, a redirected command), every log line would raise.
    """

    def write(self, s: str, /) -> int:
        return sys.stderr.write(s)

    def flush(self) -> None:
        sys.stderr.flush()


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s", stream=_CurrentStderr(), level=level.upper(), force=True
    )
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
        logger_factory=structlog.PrintLoggerFactory(file=cast(TextIO, _CurrentStderr())),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "outbound") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


bind = structlog.contextvars.bind_contextvars
unbind = structlog.contextvars.unbind_contextvars
clear = structlog.contextvars.clear_contextvars
