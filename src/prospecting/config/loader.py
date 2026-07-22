"""Assembles the validated :class:`Settings` for a run.

Precedence, lowest to highest::

    1. Section files in CONFIG_FILES      committed baseline behaviour
    2. Profile overlay                    per-environment differences (dev, test)
    3. PROSPECTING__* environment vars    per-machine and CI operational overrides

There is exactly one merge mechanism, applied uniformly to all three layers, so
"which value wins?" has a single answer that can be read off this module. Every
input — configuration directory, profile, environment, project root — is an
argument with a default rather than a hidden global read, which is what makes
the loader testable without touching real environment state.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from prospecting.config.errors import ConfigValidationError
from prospecting.config.models.settings import LoadMeta, Settings
from prospecting.config.sources import (
    ENV_CONFIG_DIR,
    ENV_PROFILE,
    collect_environment_overrides,
    deep_merge,
    read_yaml_file,
)

__all__ = ["CONFIG_FILES", "PROFILES_SUBDIR", "load_settings", "resolve_project_root"]

#: Section files merged in order. Each phase appends the file it introduces; the
#: manifest is explicit rather than a directory glob so that adding a stray YAML
#: file to ``config/`` cannot silently change how the pipeline behaves.
CONFIG_FILES: Final[tuple[str, ...]] = (
    "runtime.yaml",
    "icp.yaml",
)

#: Profile overlays live here, one file per profile: ``config/profiles/dev.yaml``.
PROFILES_SUBDIR: Final = "profiles"

#: Settings under ``paths`` that name a location and are resolved against the
#: project root when written relative.
_PATH_KEYS: Final[frozenset[str]] = frozenset(
    {
        "config_dir",
        "prompts_dir",
        "raw_dir",
        "interim_dir",
        "master_dir",
        "exports_dir",
        "checkpoint_dir",
    }
)

#: ``loader.py`` sits at ``<root>/src/prospecting/config/loader.py``.
_PROJECT_ROOT_DEPTH: Final = 3


def resolve_project_root() -> Path:
    """Return the repository root inferred from this module's location.

    Correct for an editable install and for running from a source checkout,
    which covers development and the current deployment model. A packaged
    installation should pass ``project_root`` to :func:`load_settings`
    explicitly rather than relying on this.
    """
    return Path(__file__).resolve().parents[_PROJECT_ROOT_DEPTH]


def load_settings(
    *,
    config_dir: Path | None = None,
    profile: str | None = None,
    environ: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> Settings:
    """Load, merge, and validate the configuration for a run.

    Args:
        config_dir: Directory holding the section files. Defaults to
            ``$PROSPECTING_CONFIG_DIR``, then ``<project_root>/config``.
        profile: Profile overlay to apply. Defaults to ``$PROSPECTING_PROFILE``.
            When no profile is selected, no overlay is applied; when one is
            selected, its file must exist — a typo in a profile name must not
            silently fall back to baseline behaviour.
        environ: Environment mapping to read. Defaults to :data:`os.environ`.
            Injectable so tests never mutate real process state.
        project_root: Repository root. Defaults to :func:`resolve_project_root`.

    Returns:
        A fully validated, immutable :class:`Settings`, carrying the provenance
        of its own load in :attr:`Settings.meta`.

    Raises:
        ConfigFileNotFoundError: A required section file, or a named profile
            overlay, is missing.
        ConfigParseError: A file is not valid YAML or is not a mapping.
        EnvironmentOverrideError: A ``PROSPECTING__`` variable is malformed.
        ConfigValidationError: The merged configuration violates a type or a
            rule. Every problem is reported at once so a broken file can be
            fixed in a single pass.
    """
    environment = os.environ if environ is None else environ
    root = (project_root or resolve_project_root()).resolve()
    directory = _resolve_config_dir(config_dir, environment=environment, project_root=root)
    selected_profile = profile if profile is not None else environment.get(ENV_PROFILE)

    merged: dict[str, Any] = {}
    files_loaded: list[Path] = []

    for filename in CONFIG_FILES:
        path = directory / filename
        merged = deep_merge(merged, read_yaml_file(path, required=True))
        files_loaded.append(path)

    if selected_profile:
        overlay_path = directory / PROFILES_SUBDIR / f"{selected_profile}.yaml"
        merged = deep_merge(merged, read_yaml_file(overlay_path, required=True))
        files_loaded.append(overlay_path)

    overrides, applied_variables = collect_environment_overrides(environment)
    merged = deep_merge(merged, overrides)

    merged["paths"] = _resolve_paths_section(
        merged.get("paths", {}), project_root=root, config_dir=directory
    )
    merged["meta"] = LoadMeta(
        profile=selected_profile or None,
        files_loaded=tuple(files_loaded),
        environment_overrides=applied_variables,
    ).model_dump()

    try:
        return Settings.model_validate(merged)
    except ValidationError as exc:
        raise ConfigValidationError(_describe(exc), sources=files_loaded) from exc


def _resolve_config_dir(
    explicit: Path | None,
    *,
    environment: Mapping[str, str],
    project_root: Path,
) -> Path:
    """Return the configuration directory, honouring argument then environment."""
    if explicit is not None:
        return explicit.resolve()
    from_env = environment.get(ENV_CONFIG_DIR)
    if from_env:
        return Path(from_env).resolve()
    return project_root / "config"


def _resolve_paths_section(
    section: Any,  # noqa: ANN401 - unvalidated input; shape is checked below
    *,
    project_root: Path,
    config_dir: Path,
) -> dict[str, Any]:
    """Make every configured path absolute before validation.

    Relative paths in YAML are convenient to write and portable across machines;
    relative paths at runtime silently depend on the working directory, so a
    stage started by a scheduler resolves them differently from one started in a
    shell. Resolving here means that ambiguity exists only inside this function.

    ``project_root`` and ``config_dir`` are injected rather than configured:
    both are discovered facts about where the process is running, and letting a
    file override them invites a configuration that cannot locate itself.
    """
    if not isinstance(section, dict):
        # Leave the malformed value untouched; Settings validation reports it
        # with the same message shape as every other configuration problem.
        return {"project_root": project_root, "config_dir": config_dir}

    resolved: dict[str, Any] = dict(section)
    for key in _PATH_KEYS & resolved.keys():
        value = resolved[key]
        if isinstance(value, str | Path):
            candidate = Path(value)
            resolved[key] = candidate if candidate.is_absolute() else project_root / candidate

    resolved["project_root"] = project_root
    resolved["config_dir"] = config_dir
    return resolved


def _describe(error: ValidationError) -> list[str]:
    """Render a pydantic validation error as one readable line per problem."""
    problems: list[str] = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"]) or "<root>"
        message = detail["msg"]
        if detail["type"] == "extra_forbidden":
            message = "unknown setting (check for a typo, or remove it)"
        problems.append(f"{location}: {message}")
    return problems
