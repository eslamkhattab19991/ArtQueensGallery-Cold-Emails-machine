"""Root configuration aggregate and its load provenance."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from prospecting.config.models.base import FrozenConfig
from prospecting.config.models.budget import BudgetConfig
from prospecting.config.models.checkpoint import CheckpointConfig
from prospecting.config.models.icp import IcpConfig
from prospecting.config.models.log import LogConfig
from prospecting.config.models.paths import PathsConfig
from prospecting.config.models.retry import RetryConfig
from prospecting.config.models.runtime import RuntimeConfig

__all__ = ["LoadMeta", "Settings"]


class LoadMeta(FrozenConfig):
    """Where the loaded configuration came from.

    The system records provenance for every extracted field (ARCHITECTURE.md §6);
    configuration deserves the same treatment for the same reason. "Why is
    concurrency 4?" is otherwise answered by reading three files and guessing at
    the merge order, and the answer changes silently when an environment
    variable is set on one machine and not another.
    """

    profile: str | None = Field(
        default=None, description="Profile overlay applied, or None when no overlay was used."
    )
    files_loaded: tuple[Path, ...] = Field(
        default=(), description="Configuration files merged, in the order they were applied."
    )
    environment_overrides: tuple[str, ...] = Field(
        default=(),
        description="Environment variable names that overrode a file value, in applied order.",
    )


class Settings(FrozenConfig):
    """The complete, validated configuration for one pipeline run.

    Constructed by :func:`prospecting.config.loader.load_settings` and passed
    explicitly to whatever needs it. There is deliberately no module-level
    singleton and no ``get_settings()`` accessor: a global would be mutable
    shared state, would make tests order-dependent, and would let any module
    reach for configuration without declaring that it needs it. Explicit passing
    keeps each component's dependencies visible in its signature.
    """

    paths: PathsConfig = Field(description="Filesystem locations for data, config, and outputs.")
    runtime: RuntimeConfig = Field(description="Concurrency, timeouts, and rate limits.")
    retry: RetryConfig = Field(description="Backoff policy for transient failures.")
    checkpoint: CheckpointConfig = Field(description="Checkpoint cadence and resume behaviour.")
    log: LogConfig = Field(description="Verbosity, format, and progress cadence.")
    budget: BudgetConfig = Field(description="Per-run spending ceilings.")
    icp: IcpConfig = Field(description="The tunable definition of a qualified artist.")
    meta: LoadMeta = Field(
        default_factory=LoadMeta, description="Provenance of this configuration load."
    )
