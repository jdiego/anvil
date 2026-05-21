from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "private-token",
        "private_token",
        "token",
        "secret",
        "password",
        "api_key",
        "x-api-key",
    }
)


def _redact_sensitive(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Redact secret-looking values in any log record."""

    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***"
        elif key == "headers" and isinstance(event_dict[key], dict):
            event_dict[key] = {
                k: ("***" if k.lower() in _SENSITIVE_KEYS else v)
                for k, v in event_dict[key].items()
            }
    return event_dict


def configure_logging(level: str | None = None) -> None:
    """Configure structlog to emit JSON to stderr.

    stdout is reserved for the MCP stdio transport, so all diagnostic
    output must go to stderr. Safe to call multiple times.
    """

    if structlog.is_configured():
        return

    log_level = (level or os.environ.get("ANVIL_LOG_LEVEL") or "INFO").upper()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )

    processors = _processors()

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def _processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger. Calls ``configure_logging`` on first use."""

    if not structlog.is_configured():
        configure_logging()
    return structlog.get_logger(name)  # type: ignore[no-any-return]
