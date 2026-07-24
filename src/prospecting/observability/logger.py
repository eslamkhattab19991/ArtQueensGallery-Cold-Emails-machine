"""The logging system: one configuration point, structured text or JSON output.

ARCHITECTURE.md ships a :class:`~prospecting.config.models.log.LogConfig` — level,
format, progress cadence, timestamps, cost — and this module is what turns those
settings into actual output. It follows the standard-library idiom rather than
inventing a parallel one: :func:`configure_logging` is called once at startup (by
the CLI), it configures the single ``prospecting`` logger, and every module logs
through ``logging.getLogger(__name__)`` — which, because every module lives under
the ``prospecting`` package, is automatically a child of that logger and inherits
its handler and level. No logger is threaded through call sites, and there is no
second, bespoke logging mechanism to keep in sync.

Two formats, one for each audience. ``text`` is aligned and readable in a
terminal; ``json`` emits one object per line for a log aggregator, with any
structured fields a call passed via ``extra=`` promoted to top-level keys — so a
run's progress lines are queryable ("show me every stage that failed a record")
rather than regex-scraped out of prose.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TextIO

from prospecting.config.models.log import LogConfig

__all__ = ["ROOT_LOGGER_NAME", "JsonFormatter", "TextFormatter", "configure_logging"]

#: The one logger every module's ``getLogger(__name__)`` descends from, since all
#: modules live under the ``prospecting`` package. Configuring it configures them.
ROOT_LOGGER_NAME = "prospecting"

#: Attributes the standard library puts on every ``LogRecord``. Anything on a
#: record that is *not* here was attached by a caller via ``extra=`` and is a
#: structured field worth surfacing; separating the two is how ``extra`` becomes
#: queryable JSON instead of being silently dropped.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _structured_fields(record: logging.LogRecord) -> dict[str, object]:
    """Return the fields a caller attached via ``extra=``, in the order added."""
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON object, extras promoted to top-level keys."""

    def __init__(self, *, include_timestamps: bool) -> None:
        """Configure whether each line carries an ISO-8601 UTC timestamp."""
        super().__init__()
        self._include_timestamps = include_timestamps

    def format(self, record: logging.LogRecord) -> str:
        """Serialize ``record`` to a single-line JSON object."""
        payload: dict[str, object] = {}
        if self._include_timestamps:
            payload["timestamp"] = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        payload["level"] = record.levelname
        payload["logger"] = record.name
        payload["message"] = record.getMessage()
        payload.update(_structured_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # default=str so an unexpected non-serializable extra degrades to its
        # repr rather than crashing the log call that was meant to be diagnostic.
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Render each record as an aligned, human-readable line with key=value extras."""

    def __init__(self, *, include_timestamps: bool) -> None:
        """Configure whether each line is prefixed with an ISO-8601 UTC timestamp."""
        super().__init__()
        self._include_timestamps = include_timestamps

    def format(self, record: logging.LogRecord) -> str:
        """Serialize ``record`` to one readable line."""
        segments: list[str] = []
        if self._include_timestamps:
            segments.append(datetime.fromtimestamp(record.created, tz=UTC).isoformat())
        segments.append(f"{record.levelname:<7}")
        segments.append(record.name)
        segments.append(record.getMessage())
        line = " ".join(segments)

        extras = _structured_fields(record)
        if extras:
            line += " " + " ".join(f"{key}={value}" for key, value in extras.items())
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(config: LogConfig, *, stream: TextIO | None = None) -> logging.Logger:
    """Configure the ``prospecting`` logger from ``config`` and return it.

    Idempotent: existing handlers are cleared first, so calling this twice (a
    test, then a run) does not double every line. Propagation is turned off so
    records do not also reach Python's default root handler and print twice.

    Args:
        config: Level, format, and whether timestamps appear.
        stream: Where lines are written. Defaults to ``sys.stderr`` — logs are
            diagnostics and must not pollute a piped stdout data stream.

    Returns:
        The configured ``prospecting`` logger. Modules should not use it
        directly; they log through ``logging.getLogger(__name__)`` and inherit
        this configuration.
    """
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(config.level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr if stream is None else stream)
    if config.format == "json":
        handler.setFormatter(JsonFormatter(include_timestamps=config.include_timestamps))
    else:
        handler.setFormatter(TextFormatter(include_timestamps=config.include_timestamps))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
