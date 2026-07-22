"""Shared base class for every configuration section."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["FrozenConfig"]


class FrozenConfig(BaseModel):
    """Immutable configuration section with strict key checking.

    Three settings carry the weight here:

    ``frozen``
        Configuration is read many times across a long run and must never be
        mutated in flight. Freezing removes an entire class of "who changed the
        concurrency limit mid-run?" bug and makes the object safe to share
        across threads and tasks.

    ``extra="forbid"``
        A misspelled YAML key that is silently ignored is the most expensive
        kind of configuration bug: the operator believes a setting took effect
        and the run behaves otherwise. Rejecting unknown keys converts that
        silent failure into a startup error naming the key.

    ``validate_assignment``
        Belt and braces alongside ``frozen``; if freezing is ever relaxed for a
        subclass, assignments still pass through validation.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        arbitrary_types_allowed=False,
    )
