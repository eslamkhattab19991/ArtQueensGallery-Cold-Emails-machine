"""Gallery representation."""

from __future__ import annotations

from pydantic import Field

from prospecting.domain.base import FrozenModel
from prospecting.domain.provenance import Provenance

__all__ = ["Representation"]


class Representation(FrozenModel):
    """One gallery's representation of an artist, current or former."""

    gallery: str = Field(min_length=1, description="Gallery name.")
    city: str | None = Field(default=None, description="City the gallery is based in.")
    current: bool = Field(description="Whether the representation is active.")
    provenance: Provenance = Field(description="Where this representation was read from.")
