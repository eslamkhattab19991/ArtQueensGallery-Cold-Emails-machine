"""Shared pytest fixtures and paths.

Deliberately minimal at this phase: fixtures are introduced by the phase that
needs them, so that no test depends on scaffolding whose purpose it cannot see.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from prospecting.observability.logger import ROOT_LOGGER_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_prospecting_logger() -> Iterator[None]:
    """Restore the process-global ``prospecting`` logger after every test.

    Logging is inherently global: a test that calls ``configure_logging`` leaves
    a handler on the shared logger that would otherwise capture — or double — the
    next test's output. Resetting here, once, keeps that contained so no logging
    test has to remember its own cleanup.
    """
    yield
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Absolute path to the repository root."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Directory holding frozen inputs used to keep tests deterministic."""
    return PROJECT_ROOT / "tests" / "fixtures"
