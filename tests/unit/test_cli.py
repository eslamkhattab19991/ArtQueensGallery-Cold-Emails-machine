"""Tests for the ``prospect`` command line.

The CLI is thin glue, so these check the glue: the version prints, the config
command loads and validates, a bad profile fails loudly, and ``run`` reports
honestly that no stages are wired yet rather than pretending to work.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from prospecting.cli import app
from prospecting.observability.logger import ROOT_LOGGER_NAME

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    """Restore the shared logger after any command that configures it."""
    yield
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


class TestVersion:
    def test_prints_the_installed_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "0.1.0"


class TestConfig:
    def test_prints_the_resolved_configuration(self) -> None:
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert '"rubric_version"' in result.stdout

    def test_a_missing_profile_fails_loudly(self) -> None:
        result = runner.invoke(app, ["config", "--profile", "does-not-exist"])
        assert result.exit_code == 1
        assert "does-not-exist" in result.stderr


class TestRun:
    def test_reports_that_no_stages_are_wired_yet(self) -> None:
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1
        assert "No pipeline stages are wired yet" in result.stderr


class TestHelp:
    def test_no_arguments_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # no_args_is_help exits with the help screen rather than an error.
        assert "prospecting pipeline" in result.stdout
