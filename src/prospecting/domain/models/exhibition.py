"""An exhibition entry and the aggregate statistics computed from them."""

from __future__ import annotations

from collections import Counter

from pydantic import Field

from prospecting.domain.base import FrozenModel
from prospecting.domain.enums import ExhibitionType
from prospecting.domain.provenance import Provenance

__all__ = ["Exhibition", "ExhibitionStats"]


class Exhibition(FrozenModel):
    """One exhibition an artist participated in.

    Carries a single :class:`~prospecting.domain.provenance.Provenance` for the
    whole entry rather than per-field, matching how the data is actually
    obtained: one page — a CV, a catalogue — describes one exhibition line as a
    unit, so splitting its provenance per field would not reflect how the claim
    was made.
    """

    year: int = Field(ge=1900, le=2100, description="Year the exhibition took place.")
    title: str | None = Field(default=None, description="Exhibition title, if named.")
    venue: str = Field(min_length=1, description="Gallery, museum, or fair name.")
    city: str = Field(min_length=1, description="City the exhibition took place in.")
    country: str = Field(min_length=1, description="Country the exhibition took place in.")
    type: ExhibitionType = Field(description="Solo, group, museum, biennial, or art fair.")
    provenance: Provenance = Field(description="Where this exhibition entry was read from.")


class ExhibitionStats(FrozenModel):
    """Aggregate counts and span computed from an artist's exhibition history.

    Deterministically derived from a set of :class:`Exhibition` entries — see
    :meth:`from_exhibitions` — never asserted directly by an LLM. On
    :class:`~prospecting.domain.models.artist.ArtistProfile`, the whole struct
    is wrapped in a single
    :class:`~prospecting.domain.provenance.Provenanced` with
    ``extraction_method=computed``, rather than each count carrying its own
    provenance, because every count derives from the same input list in one
    pass.
    """

    total: int = Field(ge=0)
    solo: int = Field(ge=0)
    group: int = Field(ge=0)
    museum: int = Field(ge=0)
    biennial: int = Field(ge=0)
    art_fair: int = Field(ge=0)
    first_year: int | None = Field(default=None, description="Earliest exhibition year.")
    latest_year: int | None = Field(default=None, description="Most recent exhibition year.")
    span_years: int = Field(ge=0, description="latest_year minus first_year, or 0 with no history.")
    international_count: int = Field(
        ge=0, description="Exhibitions outside the artist's own country."
    )

    @classmethod
    def from_exhibitions(
        cls, exhibitions: tuple[Exhibition, ...], *, home_country: str | None
    ) -> ExhibitionStats:
        """Compute stats from an artist's exhibition history.

        Args:
            exhibitions: The artist's exhibition history, in any order.
            home_country: The artist's own country, used to count international
                exhibitions. When ``None``, ``international_count`` is 0 rather
                than guessed — an unknown home country is not evidence that
                every exhibition was international.

        Returns:
            The computed statistics. All fields are 0 or ``None`` when
            ``exhibitions`` is empty.
        """
        if not exhibitions:
            return cls(
                total=0,
                solo=0,
                group=0,
                museum=0,
                biennial=0,
                art_fair=0,
                first_year=None,
                latest_year=None,
                span_years=0,
                international_count=0,
            )

        years = [exhibition.year for exhibition in exhibitions]
        by_type = Counter(exhibition.type for exhibition in exhibitions)
        international_count = (
            sum(1 for exhibition in exhibitions if exhibition.country != home_country)
            if home_country is not None
            else 0
        )

        first_year, latest_year = min(years), max(years)
        return cls(
            total=len(exhibitions),
            solo=by_type[ExhibitionType.SOLO],
            group=by_type[ExhibitionType.GROUP],
            museum=by_type[ExhibitionType.MUSEUM],
            biennial=by_type[ExhibitionType.BIENNIAL],
            art_fair=by_type[ExhibitionType.ART_FAIR],
            first_year=first_year,
            latest_year=latest_year,
            span_years=latest_year - first_year,
            international_count=international_count,
        )
