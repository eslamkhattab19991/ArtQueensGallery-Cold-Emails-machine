"""ArtistProfile: the canonical, cross-run record of one artist.

Accumulates across the whole pipeline. Populated progressively as an artist
moves through discovery, extraction, qualification, contact discovery,
verification, and personalization; the version stored in
``data/master/artists.jsonl`` is a self-consistent snapshot of everything
collected about the artist to date.
"""

from __future__ import annotations

from pydantic import Field

from prospecting.domain.base import FrozenModel
from prospecting.domain.enums import CareerStage, ContactStatus, Tier
from prospecting.domain.identifiers import CanonicalId, RunId
from prospecting.domain.models.contact import EmailCandidate
from prospecting.domain.models.exhibition import Exhibition, ExhibitionStats
from prospecting.domain.models.personalization import PersonalizationHook
from prospecting.domain.models.recognition import Award, PressMention, Residency
from prospecting.domain.models.representation import Representation
from prospecting.domain.provenance import Provenanced

__all__ = ["ArtistProfile"]


class ArtistProfile(FrozenModel):
    """The canonical record of one artist, aggregated across every run.

    Every field that was read from a page, inferred, or synthesized is wrapped
    in :class:`~prospecting.domain.provenance.Provenanced` (ARCHITECTURE.md
    §6). Fields that are themselves collections of provenanced entries —
    exhibitions, representation, awards, residencies, press — carry provenance
    per entry rather than wrapping the whole tuple, since each entry was
    typically read from its own source, not all of them from one.

    Deliberately excluded from this phase: the detailed per-signal
    qualification score breakdown (ARCHITECTURE.md §4.4's ``signal_scores``).
    That structure belongs to the scoring stage's own output, not to the
    artist's permanent record — a re-run under a new rubric version produces a
    new breakdown, but ``career_stage`` and ``tier`` are what the rest of the
    pipeline (contact discovery, export) actually needs to know about the
    artist. The breakdown is introduced when the scoring stage that produces it
    is built.

    No cross-field state-machine invariant is enforced here (for example,
    "``contact_status == DIRECT`` implies ``email`` is set"). This record
    represents an artist at *every* point in the pipeline, including the many
    intermediate states before contact discovery has run at all — over-
    constraining it would make legitimate partial states impossible to
    represent. The one rule that must hold at export time —
    :attr:`has_direct_contact` — is checked where records leave the system
    (ARCHITECTURE.md §4.8), not baked into the shape of the record itself.
    """

    # --- Identity -----------------------------------------------------------
    canonical_id: CanonicalId = Field(description="Stable identifier across all runs.")
    full_name: Provenanced[str] = Field(description="The artist's name.")
    gender_signal: Provenanced[str] | None = Field(
        default=None, description="Textual evidence of gender, e.g. 'female'."
    )
    country: Provenanced[str] | None = Field(default=None, description="Country, as extracted.")
    city: Provenanced[str] | None = Field(default=None, description="City, as extracted.")

    # --- Online presence ------------------------------------------------------
    website: Provenanced[str] | None = Field(default=None, description="Personal or studio site.")
    instagram: Provenanced[str] | None = Field(default=None, description="Instagram handle or URL.")
    linkedin: Provenanced[str] | None = Field(default=None, description="LinkedIn profile URL.")

    # --- Biography ---------------------------------------------------------
    biography: Provenanced[str] | None = Field(default=None)
    artist_statement: Provenanced[str] | None = Field(default=None)
    mediums: Provenanced[tuple[str, ...]] | None = Field(
        default=None, description="Normalized medium vocabulary, e.g. ('oil painting',)."
    )
    themes: Provenanced[tuple[str, ...]] | None = Field(
        default=None, description="Recurring subject matter and conceptual concerns."
    )

    # --- Qualification outcome (ARCHITECTURE.md §4.4) -----------------------
    career_stage: Provenanced[CareerStage] | None = Field(
        default=None,
        description="Inferred career stage; only mid_career and established target the ICP.",
    )
    tier: Tier | None = Field(
        default=None,
        description="Outreach tier. None until the artist has been scored and qualifies.",
    )

    # --- Contact (ARCHITECTURE.md §4.5) --------------------------------------
    contact_status: ContactStatus | None = Field(
        default=None,
        description="direct / indirect / exhausted. None before contact discovery runs.",
    )
    email: EmailCandidate | None = Field(
        default=None, description="The artist's own address. Must be ownership=ARTIST_OWNED."
    )
    gallery_email: EmailCandidate | None = Field(
        default=None, description="An indirect contact. Never a substitute for `email`."
    )

    # --- Enrichment (ARCHITECTURE.md §4.7) -----------------------------------
    exhibitions: tuple[Exhibition, ...] = Field(default=())
    exhibition_stats: Provenanced[ExhibitionStats] | None = Field(default=None)
    representation: tuple[Representation, ...] = Field(default=())
    awards: tuple[Award, ...] = Field(default=())
    residencies: tuple[Residency, ...] = Field(default=())
    press: tuple[PressMention, ...] = Field(default=())
    personalization_hooks: tuple[PersonalizationHook, ...] = Field(default=())
    recent_activity: Provenanced[str] | None = Field(default=None)
    outreach_angle: Provenanced[str] | None = Field(default=None)

    # --- Cross-run bookkeeping ------------------------------------------
    source_urls: tuple[str, ...] = Field(
        default=(), description="Every page this record has been built or corroborated from."
    )
    first_seen_run: RunId | None = Field(
        default=None, description="Run that first discovered this artist."
    )
    previously_known: bool = Field(
        default=False,
        description="Whether this artist existed in the master file before this run.",
    )

    @property
    def has_direct_contact(self) -> bool:
        """Whether this artist has a usable, artist-owned email address.

        The single check that gates inclusion in ``qualified_leads.csv``
        (ARCHITECTURE.md §4.8) — centralizing it here means the export-stage
        assertion and anything else that needs the same answer cannot drift
        apart from each other.
        """
        return self.email is not None and self.email.is_directly_contactable
