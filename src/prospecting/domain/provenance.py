"""Provenance: where a value came from, and how much to trust it.

ARCHITECTURE.md §6 promotes provenance from a convention to an enforced
structural property: every extracted, inferred, or computed value in the
domain model carries a :class:`Provenance` record, paired with its value by
:class:`Provenanced`.

ARCHITECTURE.md names the pairing wrapper ``Field[T]``. It is implemented here
as :class:`Provenanced` instead, to avoid shadowing ``pydantic.Field`` — the
function nearly every model in this package also needs to import for its other
attributes. The shape, the invariants, and the wire format are unchanged from
the architecture: ``{"value": ..., "provenance": {...}}``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from prospecting.domain.base import FrozenModel
from prospecting.domain.enums import ExtractionMethod, SourceType

__all__ = ["Provenance", "Provenanced"]

#: Extraction methods that legitimately have no source URL, because the value
#: was not read from any single page: it was derived from other already-traced
#: fields, chosen among competing values during identity resolution, or
#: supplied by a human at Stage 1. See ARCHITECTURE.md §6, "Extraction methods".
_METHODS_WITHOUT_A_SOURCE_URL = frozenset(
    {ExtractionMethod.COMPUTED, ExtractionMethod.MERGED, ExtractionMethod.MANUAL_SEED}
)


class Provenance(FrozenModel):
    """Where one value came from, how it was obtained, and how much to trust it.

    This is metadata *about* a value, not the value itself — see
    :class:`Provenanced` for the wrapper that pairs the two. Every field here
    answers a question an auditor, a GDPR data-subject request, or a future
    maintainer debugging a wrong country will ask:

    * Which page said this?              -> ``source_url``, ``source_type``
    * How was it obtained?                -> ``extraction_method``, ``extracted_by``
    * When?                                -> ``extracted_at``
    * How sure are we?                    -> ``confidence``
    * What is the actual supporting text? -> ``evidence``
    * What fed a computed value?          -> ``input_source_urls``
    """

    source_url: str | None = Field(
        default=None,
        description=(
            "Page the value was read from. Required unless the extraction "
            "method is computed, merged, or a manual seed."
        ),
    )
    source_type: SourceType = Field(description="What kind of source produced this value.")
    source_name: str | None = Field(
        default=None,
        description="Which ContactSource or evidence reader produced this, if applicable.",
    )
    extraction_method: ExtractionMethod = Field(description="How the value was obtained.")
    extracted_by: str | None = Field(
        default=None, description="Model id for LLM methods, tool name otherwise."
    )
    extracted_at: datetime = Field(
        description="When the value was obtained. Must be timezone-aware."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="How much to trust this value.")
    evidence: str | None = Field(
        default=None,
        description="The source snippet supporting the value. Required for llm_extraction.",
    )
    input_source_urls: tuple[str, ...] = Field(
        default=(), description="For synthesized or computed values: what fed them."
    )

    @model_validator(mode="after")
    def _timestamp_must_be_timezone_aware(self) -> Provenance:
        """Reject naive datetimes, which are ambiguous across a distributed pipeline."""
        if self.extracted_at.tzinfo is None:
            message = (
                f"extracted_at must be timezone-aware, got a naive datetime: "
                f"{self.extracted_at!r}. Use datetime.now(UTC) or attach a tzinfo."
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _source_url_required_unless_derived(self) -> Provenance:
        """Enforce ARCHITECTURE.md §6: source_url is required except for derived values.

        A value produced by extraction or inference that cannot point back to a
        page is exactly the kind of untraceable claim provenance exists to
        prevent.
        """
        if self.source_url is None and self.extraction_method not in _METHODS_WITHOUT_A_SOURCE_URL:
            allowed = ", ".join(sorted(m.value for m in _METHODS_WITHOUT_A_SOURCE_URL))
            message = (
                f"source_url is required for extraction_method="
                f"{self.extraction_method.value!r}. It may only be omitted for: {allowed}."
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _evidence_required_for_llm_extraction(self) -> Provenance:
        """Enforce ARCHITECTURE.md §6: llm_extraction claims must cite supporting text.

        Distinguishes a value the model read on the page (llm_extraction, backed
        by a quote) from one the model inferred (llm_inference, which is not
        required to quote anything, since there is nothing on the page to
        quote).
        """
        if self.extraction_method is ExtractionMethod.LLM_EXTRACTION and not self.evidence:
            message = (
                "evidence is required when extraction_method is llm_extraction: "
                "an extracted claim must cite the text that supports it."
            )
            raise ValueError(message)
        return self


class Provenanced[T](FrozenModel):
    """Pairs a value with the :class:`Provenance` explaining where it came from.

    Every field on :class:`~prospecting.domain.models.artist.ArtistProfile`
    that was read from a page, inferred, or synthesized is a ``Provenanced[T]``
    rather than a bare ``T`` — the type system is what makes it impossible to
    add a new field to the profile and forget to trace it.
    """

    value: T = Field(description="The extracted, inferred, or computed value.")
    provenance: Provenance = Field(description="Where the value came from.")
