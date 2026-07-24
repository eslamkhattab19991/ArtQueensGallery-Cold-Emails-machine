"""Typed configuration loading and the dependency-injection composition root.

This package is the one place permitted to know about both ports and concrete
adapters: it reads ``config/providers.yaml`` and wires implementations to
interfaces at startup. Every other layer receives its dependencies already
constructed, which is what keeps the inward layers free of vendor imports.

Configuration is loaded explicitly and passed explicitly::

    from prospecting.config import load_settings

    settings = load_settings()
    print(settings.runtime.max_concurrent_requests)

There is no module-level singleton and no ``get_settings()`` accessor by design.
A global would be mutable shared state, would make test outcomes depend on
execution order, and would let any module reach for configuration without
declaring in its signature that it needs it.

The composition root lives in :mod:`prospecting.config.container`. It is imported
from there rather than re-exported here, so importing this package stays light —
loading configuration does not pull in every adapter the container wires.
"""

from prospecting.config.errors import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    EnvironmentOverrideError,
)
from prospecting.config.loader import CONFIG_FILES, load_settings, resolve_project_root
from prospecting.config.models.budget import BudgetConfig
from prospecting.config.models.checkpoint import CheckpointConfig
from prospecting.config.models.icp import IcpConfig, SignalWeights, TierThresholds
from prospecting.config.models.log import LogConfig
from prospecting.config.models.paths import PathsConfig
from prospecting.config.models.retry import RetryConfig
from prospecting.config.models.runtime import RuntimeConfig
from prospecting.config.models.settings import LoadMeta, Settings

__all__ = [
    "CONFIG_FILES",
    "BudgetConfig",
    "CheckpointConfig",
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigParseError",
    "ConfigValidationError",
    "EnvironmentOverrideError",
    "IcpConfig",
    "LoadMeta",
    "LogConfig",
    "PathsConfig",
    "RetryConfig",
    "RuntimeConfig",
    "Settings",
    "SignalWeights",
    "TierThresholds",
    "load_settings",
    "resolve_project_root",
]
