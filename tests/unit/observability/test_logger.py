"""Tests for the logging system.

Because logging is process-global, each test configures the ``prospecting``
logger against its own in-memory stream and a fixture resets it afterwards, so
one test's configuration never leaks into another's output.
"""

from __future__ import annotations

import json
import logging
import sys
from io import StringIO

from prospecting.config.models.log import LogConfig, LogFormat, LogLevel
from prospecting.observability.logger import ROOT_LOGGER_NAME, configure_logging


def make_config(
    *,
    level: LogLevel = "INFO",
    log_format: LogFormat = "json",
    include_timestamps: bool = False,
) -> LogConfig:
    return LogConfig(
        level=level,
        format=log_format,
        progress_every_n_records=25,
        include_timestamps=include_timestamps,
        log_cost_estimates=True,
    )


def _lines(buffer: StringIO) -> list[str]:
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


class TestJsonFormat:
    def test_emits_one_valid_json_object_per_record(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(), stream=buffer)
        logging.getLogger("prospecting.test").info("hello")
        (line,) = _lines(buffer)
        parsed = json.loads(line)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "prospecting.test"
        assert parsed["message"] == "hello"

    def test_extra_fields_are_promoted_to_top_level(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(), stream=buffer)
        logging.getLogger("prospecting.test").info(
            "progress", extra={"stage": "discovery", "processed": 10}
        )
        parsed = json.loads(_lines(buffer)[0])
        assert parsed["stage"] == "discovery"
        assert parsed["processed"] == 10

    def test_timestamp_is_included_only_when_configured(self) -> None:
        with_ts = StringIO()
        configure_logging(make_config(include_timestamps=True), stream=with_ts)
        logging.getLogger("prospecting.test").info("x")
        assert "timestamp" in json.loads(_lines(with_ts)[0])

        without_ts = StringIO()
        configure_logging(make_config(include_timestamps=False), stream=without_ts)
        logging.getLogger("prospecting.test").info("x")
        assert "timestamp" not in json.loads(_lines(without_ts)[0])

    def test_a_non_serializable_extra_degrades_rather_than_crashing(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(), stream=buffer)
        logging.getLogger("prospecting.test").info("x", extra={"obj": object()})
        parsed = json.loads(_lines(buffer)[0])
        assert isinstance(parsed["obj"], str)  # rendered via default=str, not dropped


class TestTextFormat:
    def test_line_carries_level_and_message(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(log_format="text"), stream=buffer)
        logging.getLogger("prospecting.test").warning("careful")
        line = _lines(buffer)[0]
        assert "WARNING" in line
        assert "careful" in line

    def test_extras_render_as_key_value(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(log_format="text"), stream=buffer)
        logging.getLogger("prospecting.test").info("progress", extra={"processed": 5})
        assert "processed=5" in _lines(buffer)[0]


class TestLevelFiltering:
    def test_records_below_the_level_are_dropped(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(level="WARNING"), stream=buffer)
        log = logging.getLogger("prospecting.test")
        log.info("suppressed")
        log.warning("kept")
        lines = _lines(buffer)
        assert len(lines) == 1
        assert json.loads(lines[0])["message"] == "kept"


class TestConfiguration:
    def test_reconfiguring_does_not_double_handlers(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(), stream=buffer)
        configure_logging(make_config(), stream=buffer)
        logging.getLogger("prospecting.test").info("once")
        assert len(_lines(buffer)) == 1

    def test_propagation_is_disabled(self) -> None:
        configure_logging(make_config(), stream=StringIO())
        assert logging.getLogger(ROOT_LOGGER_NAME).propagate is False

    def test_child_loggers_inherit_the_configuration(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(), stream=buffer)
        logging.getLogger("prospecting.pipeline.orchestrator").info("deep")
        assert json.loads(_lines(buffer)[0])["message"] == "deep"

    def test_defaults_to_stderr_when_no_stream_is_given(self) -> None:
        logger = configure_logging(make_config())
        handler = logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr


class TestExceptionRendering:
    """A logged exception must reach the output, in either format."""

    def test_json_carries_the_traceback(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(), stream=buffer)
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("prospecting.test").exception("failed")
        parsed = json.loads(_lines(buffer)[0])
        assert "ValueError" in parsed["exception"]

    def test_text_carries_the_traceback(self) -> None:
        buffer = StringIO()
        configure_logging(make_config(log_format="text"), stream=buffer)
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("prospecting.test").exception("failed")
        assert "ValueError" in buffer.getvalue()
