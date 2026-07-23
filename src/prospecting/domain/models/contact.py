"""Contact candidates discovered by the pluggable contact-discovery engine."""

from __future__ import annotations

from pydantic import Field

from prospecting.domain.base import FrozenModel
from prospecting.domain.enums import EmailOwnership
from prospecting.domain.provenance import Provenance

__all__ = ["EmailCandidate"]


class EmailCandidate(FrozenModel):
    """One email address found by a contact source, classified by ownership.

    The same type represents both a direct artist contact and an indirect
    gallery contact — the distinguishing field is ``ownership``, classified in
    the merge layer independent of which source found the address
    (ARCHITECTURE.md §4.5.4). This is deliberate: a gallery address can surface
    from *any* source — an open-web search for an artist's name routinely
    returns her gallery's contact page — so ownership cannot be a property of
    the source that found it. It must be evaluated per candidate.

    Verification detail (MX lookup, syntax checks, the confidence band from
    ARCHITECTURE.md §4.6) is deliberately absent from this phase: it belongs to
    the Stage 6 verification schema, introduced alongside that stage's
    implementation, not to the domain-level candidate produced by discovery.
    """

    email: str = Field(min_length=3, description="The address, as found. Not yet MX-verified.")
    ownership: EmailOwnership = Field(description="Whose address this is judged to be.")
    provenance: Provenance = Field(description="Where and how this address was found.")
    corroborating_provenance: tuple[Provenance, ...] = Field(
        default=(),
        description="Independent sources that returned the same address, raising confidence.",
    )

    @property
    def is_directly_contactable(self) -> bool:
        """Whether this candidate may be used as a direct artist contact.

        ARCHITECTURE.md §4.5.5 and §4.8: only ``ARTIST_OWNED`` candidates may
        ever reach ``qualified_leads.csv``. Every other ownership class —
        including ``UNKNOWN`` — must not be treated as a successful contact.
        Centralizing the check here means every later call site (the export
        assertion, a report, a future review queue) asks the same question the
        same way, rather than each reimplementing the comparison.
        """
        return self.ownership is EmailOwnership.ARTIST_OWNED
