"""The ``SearchProvider`` port: a query becomes a list of ranked web results.

ARCHITECTURE.md §7: a search adapter turns a "query -> candidate URLs via one
provider" and explicitly does not judge quality. Serper, Brave, and Google CSE
each implement this port (§3); the discovery stage and the site-scoped and
open-web contact sources consume it without knowing which provider answered.

Note on the return type. ARCHITECTURE.md §8 describes a ``SearchProvider`` as
returning ``list[DiscoveryCandidate]``. That is the *stage's* output, not the
provider's: a raw search engine yields hits — a URL, a title, a snippet, a rank
— and turning a hit into a ``DiscoveryCandidate`` (an artist identity with
provenance) is discovery-stage logic that must not be duplicated inside every
provider adapter. So the port returns :class:`SearchHit`, and the discovery
stage lifts hits into candidates. This keeps the provider adapters thin and
interchangeable, which is the point of the port.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from prospecting.domain.base import FrozenModel

__all__ = ["SearchHit", "SearchProvider"]


class SearchHit(FrozenModel):
    """One result from a search provider, before any quality judgement.

    Intentionally close to what every search API already returns, so an adapter
    maps its provider's response into this shape with no interpretation. The
    ``engine`` field records which provider produced the hit, so that when the
    same URL is returned by two providers the corroboration layer can tell they
    are independent confirmations rather than one result counted twice.
    """

    url: str = Field(min_length=1, description="The result URL.")
    rank: int = Field(ge=1, description="1-based position in the provider's result list.")
    engine: str = Field(
        min_length=1, description="Provider id that returned this hit, e.g. 'serper'."
    )
    title: str | None = Field(
        default=None, description="The result's title, if the provider gave one."
    )
    snippet: str | None = Field(default=None, description="The provider's summary excerpt, if any.")


@runtime_checkable
class SearchProvider(Protocol):
    """Run one query against one search backend and return ranked hits."""

    name: str
    """Stable provider id, e.g. ``"serper"`` — recorded on every hit's ``engine``."""

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Return up to ``limit`` results for ``query``, ordered by rank.

        Returns an empty list when the query has no results — an ordinary
        outcome, not an error. Implementations do not filter or score; ranking
        beyond the provider's own order is the merge layer's job.
        """
        ...
