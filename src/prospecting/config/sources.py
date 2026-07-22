"""Reading, merging, and environment-overlay primitives for configuration.

Every function here is pure or takes its inputs explicitly, so the merge rules
can be tested without a filesystem, without environment variables, and without
constructing a full :class:`~prospecting.config.models.settings.Settings`.
The orchestration that combines them lives in
:mod:`prospecting.config.loader`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from prospecting.config.errors import (
    ConfigFileNotFoundError,
    ConfigParseError,
    EnvironmentOverrideError,
)

__all__ = [
    "ENV_CONFIG_DIR",
    "ENV_PROFILE",
    "ENV_VALUE_PREFIX",
    "collect_environment_overrides",
    "deep_merge",
    "read_yaml_file",
]

#: Selects which profile overlay to apply, e.g. ``PROSPECTING_PROFILE=dev``.
ENV_PROFILE = "PROSPECTING_PROFILE"

#: Overrides the directory searched for configuration files.
ENV_CONFIG_DIR = "PROSPECTING_CONFIG_DIR"

#: Prefix marking a per-value override, e.g. ``PROSPECTING__RUNTIME__MAX_CONCURRENT_REQUESTS=4``.
#: The double underscore separates path segments, which is why the prefix ends
#: with one: a single underscore is a legal character inside a setting name.
ENV_VALUE_PREFIX = "PROSPECTING__"

#: Separator between nested keys in an environment override.
_ENV_PATH_SEPARATOR = "__"


def read_yaml_file(path: Path, *, required: bool) -> dict[str, Any]:
    """Read one YAML file into a plain dictionary.

    Args:
        path: Absolute path to the file.
        required: When ``True``, a missing file is an error. When ``False``, a
            missing file yields an empty mapping — used for optional overlays
            such as profiles.

    Returns:
        The parsed mapping, or an empty mapping when the file is absent (and not
        required) or contains only comments.

    Raises:
        ConfigFileNotFoundError: ``required`` is ``True`` and the file is absent.
        ConfigParseError: The file is not valid YAML, or its top level is not a
            mapping. A YAML document that parses to a list or a bare string
            cannot be merged into the configuration tree, so it is rejected here
            rather than producing a confusing type error later.
    """
    if not path.is_file():
        if required:
            raise ConfigFileNotFoundError(path, searched_in=path.parent)
        return {}

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigParseError(path, reason=str(exc)) from exc
    except OSError as exc:
        raise ConfigParseError(path, reason=f"could not read file: {exc}") from exc

    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise ConfigParseError(
            path,
            reason=(
                f"top level must be a mapping of section names, got {type(raw).__name__}. "
                "Each configuration file contributes named sections, e.g. 'runtime:'."
            ),
        )

    return raw


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``overlay`` onto ``base``, recursing into nested mappings.

    Nested mappings merge key by key, so an overlay may change one setting
    without restating its whole section.

    Every other type — including lists — is **replaced** rather than combined.
    Concatenating lists would make removal impossible: an overlay could add a
    country to ``priority_countries`` but never drop one, and the only way to
    shrink a list would be to edit the base file that the overlay exists to
    avoid touching.

    Args:
        base: The lower-precedence mapping.
        overlay: The higher-precedence mapping; its values win.

    Returns:
        A new dictionary. Neither argument is modified, so a caller can merge a
        chain of layers without any of them being aliased into the result.
    """
    merged: dict[str, Any] = dict(base)

    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(overlay_value, Mapping):
            merged[key] = deep_merge(base_value, overlay_value)
        else:
            merged[key] = overlay_value

    return merged


def collect_environment_overrides(
    environ: Mapping[str, str],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Translate ``PROSPECTING__`` environment variables into a nested mapping.

    ``PROSPECTING__RUNTIME__MAX_CONCURRENT_REQUESTS=4`` becomes
    ``{"runtime": {"max_concurrent_requests": 4}}``.

    Values are parsed as JSON when possible, so numbers, booleans, ``null``, and
    lists all survive the round trip through the environment. A value that is
    not valid JSON is kept as a string, which is what makes plain words work
    without quoting (``PROSPECTING__LOG__LEVEL=DEBUG``).

    Args:
        environ: The environment to read. Injected rather than read from
            :mod:`os` so that tests never mutate real process state.

    Returns:
        A tuple of the nested override mapping and the variable names applied,
        in sorted order. The names are recorded in
        :class:`~prospecting.config.models.settings.LoadMeta` so an operator can
        see which settings came from the environment rather than from a file.

    Raises:
        EnvironmentOverrideError: A variable carries the prefix but no key path
            (``PROSPECTING__=x``), or a path segment is empty
            (``PROSPECTING__RUNTIME____TIMEOUT=x``). Both are typos that would
            otherwise be discarded silently, leaving the operator convinced an
            override had taken effect.
    """
    overrides: dict[str, Any] = {}
    applied: list[str] = []

    for name in sorted(environ):
        if not name.startswith(ENV_VALUE_PREFIX):
            continue

        path_part = name[len(ENV_VALUE_PREFIX) :]
        if not path_part:
            raise EnvironmentOverrideError(
                name,
                reason=(
                    "no setting path after the prefix; expected "
                    f"{ENV_VALUE_PREFIX}SECTION{_ENV_PATH_SEPARATOR}KEY"
                ),
            )

        segments = [segment.lower() for segment in path_part.split(_ENV_PATH_SEPARATOR)]
        if any(not segment for segment in segments):
            raise EnvironmentOverrideError(
                name,
                reason=(
                    "empty path segment, which usually means a doubled separator; expected "
                    f"{ENV_VALUE_PREFIX}SECTION{_ENV_PATH_SEPARATOR}KEY"
                ),
            )

        _assign_nested(overrides, segments, _parse_scalar(environ[name]), variable=name)
        applied.append(name)

    return overrides, tuple(applied)


def _parse_scalar(raw: str) -> Any:  # noqa: ANN401 - configuration values are heterogeneous
    """Parse an environment value as JSON, falling back to the literal string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _assign_nested(
    target: dict[str, Any],
    segments: list[str],
    value: Any,  # noqa: ANN401 - configuration values are heterogeneous
    *,
    variable: str,
) -> None:
    """Assign ``value`` at the nested ``segments`` path within ``target``.

    Raises:
        EnvironmentOverrideError: An intermediate segment already holds a
            non-mapping value, meaning two overrides disagree about the shape of
            the tree (``PROSPECTING__LOG=x`` alongside ``PROSPECTING__LOG__LEVEL=y``).
    """
    cursor = target
    for segment in segments[:-1]:
        existing = cursor.get(segment)
        if existing is None:
            existing = {}
            cursor[segment] = existing
        elif not isinstance(existing, dict):
            raise EnvironmentOverrideError(
                variable,
                reason=(
                    f"path segment {segment!r} was already set to a non-mapping value by "
                    "another override; two variables disagree about the configuration shape"
                ),
            )
        cursor = existing

    cursor[segments[-1]] = value
