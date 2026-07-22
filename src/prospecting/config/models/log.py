"""Logging and progress-reporting settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from prospecting.config.models.base import FrozenConfig

__all__ = ["LogConfig", "LogFormat", "LogLevel"]

#: Accepted logging levels, mirroring the standard library's named levels.
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

#: ``text`` is readable in a terminal; ``json`` is parseable by log aggregators.
LogFormat = Literal["text", "json"]


class LogConfig(FrozenConfig):
    """Verbosity, output format, and progress cadence.

    Progress cadence is separate from log level because they answer different
    questions. Level controls *what* is worth recording; cadence controls how
    often a long-running stage reassures the operator that it is still moving.
    """

    level: LogLevel = Field(description="Minimum severity that reaches the log.")
    format: LogFormat = Field(description="Human-readable text or machine-parseable JSON.")
    progress_every_n_records: int = Field(
        ge=1, description="Records between progress lines during a long stage."
    )
    include_timestamps: bool = Field(description="Whether each line carries an ISO-8601 timestamp.")
    log_cost_estimates: bool = Field(
        description="Whether progress lines include running spend for the stage."
    )
