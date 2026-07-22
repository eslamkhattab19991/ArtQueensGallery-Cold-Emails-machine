"""Filesystem locations used by the pipeline."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator

from prospecting.config.models.base import FrozenConfig

__all__ = ["PathsConfig"]


class PathsConfig(FrozenConfig):
    """Absolute filesystem locations for configuration, data, and outputs.

    Paths are written relative to the project root in YAML and resolved to
    absolute paths by the loader before validation. Storing them absolute means
    no downstream module has to know what the current working directory is —
    a stage invoked from a scheduler and one invoked from a shell resolve
    identically.

    Run-scoped directories are derived rather than configured: a run identifier
    is a runtime value, so ``data/interim/<run_id>`` cannot be a static setting.
    """

    project_root: Path = Field(
        description="Repository root; all relative paths resolve against it."
    )
    config_dir: Path = Field(description="Directory holding the YAML configuration files.")
    prompts_dir: Path = Field(description="Directory holding prompt templates.")
    raw_dir: Path = Field(description="Cached crawl payloads, addressed by content hash.")
    interim_dir: Path = Field(description="Per-stage JSONL output, one subdirectory per run.")
    master_dir: Path = Field(description="Cross-run master artist file and suppression list.")
    exports_dir: Path = Field(description="Final CSV deliverables, one subdirectory per run.")
    checkpoint_dir: Path = Field(description="Stage checkpoints and failure logs.")

    @field_validator("*")
    @classmethod
    def _must_be_absolute(cls, value: Path) -> Path:
        """Reject relative paths, which would depend on the working directory."""
        if not value.is_absolute():
            message = (
                f"Path must be absolute after loading, got {value!r}. "
                "The loader resolves relative paths against the project root; "
                "constructing PathsConfig directly requires absolute paths."
            )
            raise ValueError(message)
        return value

    def raw_for_run(self, run_id: str) -> Path:
        """Return the cache directory for ``run_id``."""
        return self.raw_dir / run_id

    def interim_for_run(self, run_id: str) -> Path:
        """Return the stage-output directory for ``run_id``."""
        return self.interim_dir / run_id

    def exports_for_run(self, run_id: str) -> Path:
        """Return the deliverables directory for ``run_id``."""
        return self.exports_dir / run_id

    def checkpoints_for_run(self, run_id: str) -> Path:
        """Return the checkpoint directory for ``run_id``."""
        return self.checkpoint_dir / run_id
