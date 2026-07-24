"""The ``LeadRepository`` port: the durable, cross-run store of artists.

ARCHITECTURE.md §3: ``data/master/artists.jsonl`` is "the durable cross-run
asset" — the compounding database that makes the system more valuable every run
rather than a list thrown away after one. This port is how the pipeline reads
and updates it.

It deals only in :class:`~prospecting.domain.models.artist.ArtistProfile`, a pure
domain model, so unlike :mod:`~prospecting.ports.stage_store` it needs nothing
from ``schemas``: the master record is the artist, not an in-flight envelope.

Synchronous, for the same reason as the stage store: identity resolution and the
export stage read and write the master file sequentially, so async would add
ceremony without concurrency.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol, runtime_checkable

from prospecting.domain.identifiers import CanonicalId
from prospecting.domain.models.artist import ArtistProfile

__all__ = ["LeadRepository"]


@runtime_checkable
class LeadRepository(Protocol):
    """Read and update the master artist database that persists across runs."""

    def exists(self, canonical_id: CanonicalId) -> bool:
        """Whether an artist with this id is already in the master store.

        The cheap check discovery uses to skip an artist it has seen before, so
        a re-run spends its budget on new ground instead of re-tracing the known.
        """
        ...

    def get(self, canonical_id: CanonicalId) -> ArtistProfile | None:
        """Return the stored profile for ``canonical_id``, or ``None`` if absent."""
        ...

    def upsert(self, profiles: Iterable[ArtistProfile]) -> int:
        """Insert or update ``profiles`` by canonical id, returning the count applied.

        Update-in-place, never append-duplicate: identity resolution
        (ARCHITECTURE.md §4.3c) has already decided that two records are the same
        artist, so a returning artist replaces its prior snapshot rather than
        creating a second row that would double-count the lead.
        """
        ...

    def iter_all(self) -> Iterator[ArtistProfile]:
        """Yield every stored artist.

        Named ``iter_all`` rather than ``all`` to avoid shadowing the builtin,
        and returning an iterator rather than a list because the master file is
        expected to outgrow comfortable memory as the asset compounds.
        """
        ...
