"""Shared base class for domain models.

Mirrors ``prospecting.config.models.base.FrozenConfig`` in spirit — frozen,
strict, no arbitrary types — but is defined independently within the domain
package. The domain layer must import nothing from ``prospecting.config``
(ARCHITECTURE.md §3: the domain "imports nothing from this package"), so the
two base classes cannot share an implementation across that boundary even
though they express the same idea.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["FrozenModel"]


class FrozenModel(BaseModel):
    """Immutable, strictly-typed base for every domain model.

    ``frozen=True``
        A domain record is a snapshot, not a mutable object — "updating" an
        artist's country means constructing a new
        :class:`~prospecting.domain.models.artist.ArtistProfile`, never
        assigning into an existing one. This is what keeps a record safe to
        pass between concurrently running stages and to use as a value in a
        set or dict key during identity resolution.

    ``extra="forbid"``
        A field that does not exist on the model must fail loudly at
        construction, not be silently dropped — the same reasoning as the
        configuration layer's base class, applied to data instead of settings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
