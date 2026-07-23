"""Awards, residencies, and press coverage — career recognition signals.

Grouped in one module because the three share an identical shape (a name, an
optional year, an optional granting or hosting institution, and provenance) and
play the same role in the qualification rubric: evidence of external
recognition, feeding ``professional_presence`` and ``career_stage_fit``
(ARCHITECTURE.md §4.4).
"""

from __future__ import annotations

from pydantic import Field

from prospecting.domain.base import FrozenModel
from prospecting.domain.provenance import Provenance

__all__ = ["Award", "PressMention", "Residency"]


class Award(FrozenModel):
    """A prize or award the artist has received."""

    name: str = Field(min_length=1, description="Award name.")
    year: int | None = Field(default=None, ge=1900, le=2100)
    institution: str | None = Field(default=None, description="Body that granted the award.")
    provenance: Provenance = Field(description="Where this award was read from.")


class Residency(FrozenModel):
    """An artist residency the artist has completed or is undertaking."""

    name: str = Field(min_length=1, description="Residency name.")
    year: int | None = Field(default=None, ge=1900, le=2100)
    institution: str | None = Field(default=None, description="Body that hosted the residency.")
    provenance: Provenance = Field(description="Where this residency was read from.")


class PressMention(FrozenModel):
    """A piece of press coverage about the artist."""

    publication: str = Field(min_length=1, description="Publication name.")
    year: int | None = Field(default=None, ge=1900, le=2100)
    title: str | None = Field(default=None, description="Headline or article title.")
    url: str | None = Field(default=None, description="Link to the coverage, if available.")
    provenance: Provenance = Field(description="Where this press mention was read from.")
