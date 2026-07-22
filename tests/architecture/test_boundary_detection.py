"""Tests for the import-detection helpers used by the boundary tests.

A guard that silently detects nothing passes just as quietly as a guard that
works. These tests prove the detection logic in ``test_layer_boundaries`` finds
the violations it claims to find, using synthetic source files rather than the
real package.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture.test_layer_boundaries import _full_imports, _imported_roots


def _write(tmp_path: Path, source: str) -> Path:
    module = tmp_path / "sample.py"
    module.write_text(source, encoding="utf-8")
    return module


@pytest.mark.architecture
def test_detects_plain_import(tmp_path: Path) -> None:
    module = _write(tmp_path, "import anthropic\n")
    assert _imported_roots(module) == {"anthropic"}


@pytest.mark.architecture
def test_detects_dotted_import(tmp_path: Path) -> None:
    module = _write(tmp_path, "import prospecting.adapters.crawl.firecrawl\n")
    assert _imported_roots(module) == {"prospecting"}
    assert _full_imports(module) == {"prospecting.adapters.crawl.firecrawl"}


@pytest.mark.architecture
def test_detects_from_import(tmp_path: Path) -> None:
    module = _write(tmp_path, "from prospecting.adapters.llm import client\n")
    assert _full_imports(module) == {"prospecting.adapters.llm"}


@pytest.mark.architecture
def test_detects_aliased_import(tmp_path: Path) -> None:
    module = _write(tmp_path, "import httpx as http_client\n")
    assert _imported_roots(module) == {"httpx"}


@pytest.mark.architecture
def test_detects_multiple_imports_on_one_statement(tmp_path: Path) -> None:
    module = _write(tmp_path, "import json, httpx\n")
    assert _imported_roots(module) == {"json", "httpx"}


@pytest.mark.architecture
def test_detects_imports_nested_inside_functions(tmp_path: Path) -> None:
    """A deferred import is still a dependency; hiding it in a function is not an escape."""
    module = _write(
        tmp_path,
        "def load() -> None:\n    import firecrawl\n    del firecrawl\n",
    )
    assert _imported_roots(module) == {"firecrawl"}


@pytest.mark.architecture
def test_detects_imports_inside_try_blocks(tmp_path: Path) -> None:
    module = _write(
        tmp_path,
        "try:\n    import pandas\nexcept ImportError:\n    pandas = None\n",
    )
    assert _imported_roots(module) == {"pandas"}


@pytest.mark.architecture
def test_ignores_relative_imports_in_full_import_scan(tmp_path: Path) -> None:
    """Relative imports have their own dedicated check and no resolvable root here."""
    module = _write(tmp_path, "from . import sibling\nfrom ..other import thing\n")
    assert _full_imports(module) == set()


@pytest.mark.architecture
def test_ignores_strings_that_merely_mention_a_module(tmp_path: Path) -> None:
    """AST parsing, not text matching — a docstring naming a module is not an import."""
    module = _write(tmp_path, '"""This module explains why we do not import anthropic."""\n')
    assert _imported_roots(module) == set()
