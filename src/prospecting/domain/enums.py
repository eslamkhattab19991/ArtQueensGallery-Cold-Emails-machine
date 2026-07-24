"""Controlled vocabularies used throughout the domain model.

Every enum here backs a field whose values drive branching logic elsewhere in
the pipeline (a hard filter, an export decision, a merge rule). Where a value
is compared, counted, or serialized to JSONL across runs, it is an enum member
here rather than a free string — a typo in a string constant fails silently;
a typo in an enum member name fails at import time.

Values are pinned explicitly (``SOLO = "solo"``) rather than left to derive
from the member name, because the string is also the wire format written to
JSONL and read back by a later run. Renaming a Python identifier must never
silently change what is on disk.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CareerStage",
    "ContactMethod",
    "ContactStatus",
    "EmailOwnership",
    "ExhibitionType",
    "ExtractionMethod",
    "RejectReason",
    "SourceTier",
    "SourceType",
    "Tier",
]


class CareerStage(StrEnum):
    """Where an artist sits in their professional trajectory.

    ARCHITECTURE.md §4.4: only :attr:`MID_CAREER` and :attr:`ESTABLISHED` are
    in the Ideal Artist Profile's target band; every other value scores zero on
    the ``career_stage_fit`` signal. The full set exists so that a rejection can
    say *why* rather than just *no* — "student" and "celebrity" are both
    disqualifying, but for opposite reasons, and that distinction matters when
    tuning the rubric later.
    """

    STUDENT = "student"
    HOBBYIST = "hobbyist"
    RECENT_GRADUATE = "recent_graduate"
    EMERGING = "emerging"
    MID_CAREER = "mid_career"
    ESTABLISHED = "established"
    CELEBRITY = "celebrity"


class Tier(StrEnum):
    """Outreach tier assigned to a lead that has passed qualification.

    ARCHITECTURE.md §4.4 describes a fourth outcome, "reject", alongside A/B/C
    in its threshold table — but a rejected artist never receives a tier. It
    receives a :class:`RejectReason` instead and is written to
    ``rejected.csv``. Modelling ``Tier`` with only the three qualifying values
    keeps "has a tier" synonymous with "qualified", which is the invariant the
    export stage relies on.
    """

    A = "A"
    B = "B"
    C = "C"


class ContactStatus(StrEnum):
    """The outcome of running the contact-discovery engine on one artist.

    ARCHITECTURE.md §4.5.5. ``INDIRECT`` means only a gallery or institutional
    address was found — never a substitute for a direct artist contact, and
    structurally barred from ``qualified_leads.csv`` (§4.8).
    """

    DIRECT = "direct"
    INDIRECT = "indirect"
    EXHAUSTED = "exhausted"


class ContactMethod(StrEnum):
    """A channel through which an artist can be contacted.

    ARCHITECTURE.md §4.5.1: a :class:`~prospecting.ports.contact_source.ContactSource`
    declares which of these it ``provides``. The distinction that matters for
    the business contract (ARCHITECTURE.md §0) is that **only** :attr:`EMAIL`
    can complete a lead. A phone number, a contact form, or a social handle is
    enrichment — genuinely useful for outreach, especially for a qualified
    artist whose direct email was never found, but never a substitute for a
    verified artist-owned email and never a reason to count an artist as a
    completed lead.

    Because the enrichment channels cannot promote an artist to a completed
    lead, they do not need the strict ownership classification that email
    requires (§4.5.4): the ownership machinery exists to protect the completion
    KPI, and these channels do not touch it.
    """

    EMAIL = "email"
    PHONE = "phone"
    FORM = "form"
    SOCIAL_HANDLE = "social_handle"


class EmailOwnership(StrEnum):
    """Who an email address actually belongs to.

    ARCHITECTURE.md §4.5.4: classified per candidate in the merge layer,
    independent of which source found the address — a gallery's contact page
    can surface from a plain web search just as easily as from a dedicated
    gallery-page source, so ownership cannot be inferred from provenance alone.
    """

    ARTIST_OWNED = "artist_owned"
    GALLERY = "gallery"
    INSTITUTION = "institution"
    AGGREGATOR = "aggregator"
    UNKNOWN = "unknown"


class ExtractionMethod(StrEnum):
    """How a value was obtained, for the :class:`~prospecting.domain.provenance.Provenance` record.

    ARCHITECTURE.md §6. The distinction that matters most is
    :attr:`LLM_EXTRACTION` versus :attr:`LLM_INFERENCE`: a value the model read
    off the page and a value the model concluded from context are different
    kinds of claim, and conflating them is how a prospecting database quietly
    fills with confident fiction.
    """

    MAILTO_HREF = "mailto_href"
    REGEX_MATCH = "regex_match"
    STRUCTURED_PARSE = "structured_parse"
    DNS_LOOKUP = "dns_lookup"
    LLM_EXTRACTION = "llm_extraction"
    LLM_INFERENCE = "llm_inference"
    LLM_SYNTHESIS = "llm_synthesis"
    COMPUTED = "computed"
    MERGED = "merged"
    MANUAL_SEED = "manual_seed"


class SourceTier(StrEnum):
    """Cost tier of a contact-discovery source, for the tiered-parallel scheduler.

    ARCHITECTURE.md §4.5.2. Values are uppercase to match the wire format shown
    in the architecture's ``ContactedArtist`` examples (``"tiers_run": ["CACHED", "CHEAP"]``).
    """

    CACHED = "CACHED"
    CHEAP = "CHEAP"
    MODERATE = "MODERATE"
    EXPENSIVE = "EXPENSIVE"


class RejectReason(StrEnum):
    """Why an artist failed qualification.

    ARCHITECTURE.md §4.4: the four hard filters (gender, geography, name,
    suppression), plus rejection by total score. Career-stage mismatch is
    deliberately absent — it is not a hard filter but a scored signal, so a
    student or celebrity artist is rejected via :attr:`SCORE_BELOW_THRESHOLD`,
    not a dedicated reason.
    """

    GENDER_NOT_CONFIRMED_FEMALE = "gender_not_confirmed_female"
    OUTSIDE_PRIORITY_GEOGRAPHY = "outside_priority_geography"
    MISSING_FULL_NAME = "missing_full_name"
    SUPPRESSED = "suppressed"
    SCORE_BELOW_THRESHOLD = "score_below_threshold"


class SourceType(StrEnum):
    """The kind of source a :class:`~prospecting.domain.provenance.Provenance` points to.

    ARCHITECTURE.md §6. Not explicitly named in the architecture's ``enums.py``
    file-listing comment, which lists a representative rather than exhaustive
    set — but required structurally, since ``Provenance.source_type`` is
    specified in the same section with this exact set of values.
    """

    ARTIST_WEBSITE = "artist_website"
    GALLERY_WEBSITE = "gallery_website"
    SEARCH_RESULT = "search_result"
    DIRECTORY = "directory"
    SOCIAL = "social"
    PDF_DOCUMENT = "pdf_document"
    EVIDENCE_PLATFORM = "evidence_platform"
    DERIVED = "derived"


class ExhibitionType(StrEnum):
    """The kind of exhibition an artist participated in.

    ARCHITECTURE.md §4.7's ``exhibition_stats`` counts exactly these five
    categories (``total, solo, group, museum, biennial, art_fair``), which is
    where this closed set comes from — it is not listed as a named enum in the
    architecture, but the categories it counts are fixed and used for scoring,
    so leaving them as free strings would let a typo silently exclude an
    exhibition from every count that reads it.
    """

    SOLO = "solo"
    GROUP = "group"
    MUSEUM = "museum"
    BIENNIAL = "biennial"
    ART_FAIR = "art_fair"
