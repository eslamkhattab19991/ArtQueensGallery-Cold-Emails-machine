"""Checkpointing and resume behaviour."""

from __future__ import annotations

from pydantic import Field

from prospecting.config.models.base import FrozenConfig

__all__ = ["CheckpointConfig"]


class CheckpointConfig(FrozenConfig):
    """How often progress is durably recorded, and how a run resumes.

    Flush frequency trades durability against I/O. Flushing every record makes a
    crash cost nothing but slows the stage; flushing every thousand risks
    repeating a thousand records' worth of paid API calls. The right value
    depends on the cost per record, which differs per stage, so it is
    configuration rather than a constant.
    """

    enabled: bool = Field(
        description="Whether stages write checkpoints. Disabling makes runs non-resumable."
    )
    flush_every_n_records: int = Field(
        ge=1, description="Records processed between durable checkpoint writes."
    )
    resume_by_default: bool = Field(
        description="Whether a stage re-run resumes from its checkpoint rather than restarting."
    )
    record_failures_separately: bool = Field(
        description="Whether failed records go to a retry queue distinct from the main output."
    )
    checkpoint_filename: str = Field(
        min_length=1, description="Checkpoint filename within a run's checkpoint directory."
    )
    failure_filename: str = Field(
        min_length=1, description="Failed-record filename within a run's checkpoint directory."
    )
