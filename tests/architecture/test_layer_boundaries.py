"""Structural tests enforcing the layering rules in ARCHITECTURE.md.

These run in the normal test suite so that a boundary violation fails at the same
moment a broken unit test would, rather than at review time. The Import Linter
contracts in ``pyproject.toml`` cover the same ground for CI; this module makes
the two most important rules enforceable via ``pytest`` alone, and adds checks
that Import Linter cannot express.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "prospecting"

#: Third-party modules that must never appear in the domain layer. The domain is
#: the one layer that outlives every provider decision, so it stays free of
#: vendor SDKs, network clients, and I/O libraries.
INFRASTRUCTURE_MODULES = frozenset(
    {
        "anthropic",
        "firecrawl",
        "httpx",
        "requests",
        "urllib",
        "urllib3",
        "openpyxl",
        "pandas",
        "dns",
        "sqlite3",
        "yaml",
        "aiohttp",
        "boto3",
    }
)


def _python_modules(package: str) -> list[Path]:
    """Return every Python source file under ``src/prospecting/<package>``."""
    return sorted((PACKAGE_ROOT / package).rglob("*.py"))


def _imported_roots(module_path: Path) -> set[str]:
    """Return the root name of every module imported by ``module_path``.

    Uses the AST rather than importing the module, so the check works on code
    that has unmet runtime dependencies and never executes project code.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    return roots


def _full_imports(module_path: Path) -> set[str]:
    """Return the fully qualified name of every module imported by ``module_path``."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)

    return imports


@pytest.mark.architecture
def test_domain_imports_nothing_from_the_package() -> None:
    """The domain layer must not depend on any other layer.

    ARCHITECTURE.md §3: "Why ``domain/`` imports nothing. It is the one layer that
    must survive every provider change, storage change, and refactor."
    """
    violations: list[str] = []

    for module in _python_modules("domain"):
        for imported in _full_imports(module):
            if imported.startswith("prospecting.") and not imported.startswith(
                "prospecting.domain"
            ):
                violations.append(f"{module.relative_to(PACKAGE_ROOT)} imports {imported}")

    assert not violations, "Domain layer must not import other layers:\n" + "\n".join(violations)


@pytest.mark.architecture
def test_domain_imports_no_infrastructure_libraries() -> None:
    """The domain layer must not depend on vendor SDKs or I/O libraries."""
    violations: list[str] = []

    for module in _python_modules("domain"):
        for root in _imported_roots(module) & INFRASTRUCTURE_MODULES:
            violations.append(f"{module.relative_to(PACKAGE_ROOT)} imports {root}")

    assert not violations, (
        "Domain layer must stay free of infrastructure dependencies:\n" + "\n".join(violations)
    )


@pytest.mark.architecture
def test_ports_depend_only_on_the_domain() -> None:
    """Ports declare capabilities; they may reference the domain and nothing else."""
    violations: list[str] = []
    allowed = ("prospecting.domain", "prospecting.ports")

    for module in _python_modules("ports"):
        for imported in _full_imports(module):
            if imported.startswith("prospecting.") and not imported.startswith(allowed):
                violations.append(f"{module.relative_to(PACKAGE_ROOT)} imports {imported}")

    assert not violations, "Ports may only depend on the domain:\n" + "\n".join(violations)


@pytest.mark.architecture
@pytest.mark.parametrize("layer", ["pipeline", "contact", "enrichment", "scoring"])
def test_inward_layers_never_import_concrete_adapters(layer: str) -> None:
    """Business layers depend on ports; adapters are injected by the composition root.

    This is what allows the pipeline and the contact engine to be tested with
    fakes and zero network access.
    """
    violations: list[str] = []

    for module in _python_modules(layer):
        for imported in _full_imports(module):
            if imported.startswith("prospecting.adapters"):
                violations.append(f"{module.relative_to(PACKAGE_ROOT)} imports {imported}")

    assert not violations, f"{layer!r} must depend on ports, not concrete adapters:\n" + "\n".join(
        violations
    )


@pytest.mark.architecture
def test_adapters_contain_no_business_logic_imports() -> None:
    """Adapters translate for one external system; decisions belong further in."""
    forbidden = (
        "prospecting.pipeline",
        "prospecting.contact",
        "prospecting.enrichment",
        "prospecting.scoring",
        "prospecting.identity",
        "prospecting.compliance",
    )
    violations: list[str] = []

    for module in _python_modules("adapters"):
        for imported in _full_imports(module):
            if imported.startswith(forbidden):
                violations.append(f"{module.relative_to(PACKAGE_ROOT)} imports {imported}")

    assert not violations, "Adapters must not reach into business layers:\n" + "\n".join(violations)


@pytest.mark.architecture
def test_no_relative_imports_anywhere() -> None:
    """Absolute imports only, so a module's dependencies are readable in isolation."""
    violations: list[str] = []

    for module in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                violations.append(f"{module.relative_to(PACKAGE_ROOT)}:{node.lineno}")

    assert not violations, "Relative imports are banned:\n" + "\n".join(violations)


@pytest.mark.architecture
def test_every_package_declares_its_responsibility() -> None:
    """Every package documents what it owns, so its boundary is reviewable.

    ARCHITECTURE.md §7 assigns each module a single responsibility. A package
    whose ``__init__`` cannot state that responsibility has not earned its place
    in the tree.
    """
    undocumented: list[str] = []

    for init_file in PACKAGE_ROOT.rglob("__init__.py"):
        tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
        docstring = ast.get_docstring(tree)
        if not docstring or len(docstring.strip()) < 40:
            undocumented.append(str(init_file.relative_to(PACKAGE_ROOT)))

    assert not undocumented, "Every package must document its responsibility:\n" + "\n".join(
        undocumented
    )


@pytest.mark.architecture
def test_no_todo_comments_without_an_issue_reference() -> None:
    """A TODO without a tracking reference is a defect nobody has agreed to fix."""
    pattern = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b(?!.*(#\d+|[A-Z]+-\d+))", re.IGNORECASE)
    violations: list[str] = []

    for module in PACKAGE_ROOT.rglob("*.py"):
        for lineno, line in enumerate(module.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{module.relative_to(PACKAGE_ROOT)}:{lineno}: {line.strip()}")

    assert not violations, (
        "TODO/FIXME comments require an issue reference (e.g. '# TODO(#42): ...'):\n"
        + "\n".join(violations)
    )
