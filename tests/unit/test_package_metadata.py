"""Smoke tests: the package imports cleanly and declares coherent metadata."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import prospecting

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_package_imports() -> None:
    assert prospecting is not None


def test_version_is_semver() -> None:
    assert SEMVER.match(prospecting.__version__), (
        f"Expected semantic version, got {prospecting.__version__!r}"
    )


def test_version_matches_pyproject() -> None:
    """A drifting version silently mislabels every artefact built from it."""
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert prospecting.__version__ == metadata["project"]["version"]


def test_package_ships_type_information() -> None:
    """``py.typed`` is what makes the strict annotations visible to consumers."""
    marker = Path(prospecting.__file__).parent / "py.typed"
    assert marker.exists(), "PEP 561 marker missing; downstream type checking would silently pass"
