"""Logging configuration for mesa-mcp.

``stdio`` transports MUST emit human-readable logs to *stderr* — anything on
stdout would corrupt the MCP framing. Non-stdio transports get JSON logs so
they ship cleanly into log aggregators.

Convention (also documented in CLAUDE.md):
    **Never log credentials.** No passwords, no bearer tokens, no PAM secrets,
    no OIDC client secrets. Pass them through structlog's context only after
    redaction.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def setup_logging(level: str = "info", transport: str = "stdio") -> None:
    """Initialize ``structlog`` for the chosen transport.

    Parameters
    ----------
    level:
        One of ``debug``/``info``/``warning``/``error``/``critical`` (case
        insensitive). Unknown values fall back to ``info``.
    transport:
        ``"stdio"`` uses a console renderer (so devs reading stderr see
        human-friendly lines); anything else uses a JSON renderer.
    """
    log_level = _LEVEL_MAP.get(level.lower(), logging.INFO)

    # Stdlib logging configuration — structlog wraps it, but we still need a
    # root handler so non-structlog libraries (mcp, irods, requests) emit too.
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stderr,
        force=True,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderer: Any
    if transport == "stdio":
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
