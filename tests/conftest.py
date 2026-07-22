"""Shared pytest fixtures and paths.

Deliberately minimal at this phase: fixtures are introduced by the phase that
needs them, so that no test depends on scaffolding whose purpose it cannot see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Absolute path to the repository root."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Directory holding frozen inputs used to keep tests deterministic."""
    return PROJECT_ROOT / "tests" / "fixtures"
