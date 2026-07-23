"""Tests for Provenance and the Provenanced[T] wrapper.

These cover the three rules ARCHITECTURE.md §6 promotes from convention to
enforced structure. Each one exists to stop a specific way an untraceable or
misleading claim could enter the master file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from prospecting.domain.enums import ExtractionMethod, SourceType
from prospecting.domain.provenance import Provenance, Provenanced
from tests.support.factories import make_provenance

#: Methods that legitimately have no single source page, per ARCHITECTURE.md §6.
DERIVED_METHODS = [
    ExtractionMethod.COMPUTED,
    ExtractionMethod.MERGED,
    ExtractionMethod.MANUAL_SEED,
]

#: Methods that read or infer from a specific page and must cite it.
PAGE_BACKED_METHODS = [
    ExtractionMethod.MAILTO_HREF,
    ExtractionMethod.REGEX_MATCH,
    ExtractionMethod.STRUCTURED_PARSE,
    ExtractionMethod.DNS_LOOKUP,
    ExtractionMethod.LLM_EXTRACTION,
    ExtractionMethod.LLM_INFERENCE,
    ExtractionMethod.LLM_SYNTHESIS,
]


class TestTimestampMustBeTimezoneAware:
    """A naive timestamp is ambiguous once records cross machines or timezones."""

    def test_accepts_utc(self) -> None:
        provenance = make_provenance(extracted_at=datetime(2026, 7, 23, tzinfo=UTC))
        assert provenance.extracted_at.tzinfo is not None

    def test_accepts_a_non_utc_offset(self) -> None:
        """Any aware datetime is fine; the rule is about ambiguity, not about UTC."""
        tokyo = timezone(timedelta(hours=9))
        provenance = make_provenance(extracted_at=datetime(2026, 7, 23, tzinfo=tokyo))
        assert provenance.extracted_at.utcoffset() == timedelta(hours=9)

    def test_rejects_a_naive_datetime(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_provenance(extracted_at=datetime(2026, 7, 23))  # noqa: DTZ001


class TestSourceUrlRequiredUnlessDerived:
    """ARCHITECTURE.md §6: an extracted claim must be able to point back to a page."""

    @pytest.mark.parametrize("method", PAGE_BACKED_METHODS)
    def test_page_backed_methods_require_a_source_url(self, method: ExtractionMethod) -> None:
        with pytest.raises(ValidationError, match="source_url is required"):
            make_provenance(source_url=None, extraction_method=method, evidence="x")

    @pytest.mark.parametrize("method", DERIVED_METHODS)
    def test_derived_methods_may_omit_the_source_url(self, method: ExtractionMethod) -> None:
        """A computed or merged value derives from other already-traced fields."""
        provenance = make_provenance(
            source_url=None,
            source_type=SourceType.DERIVED,
            extraction_method=method,
            evidence=None,
        )
        assert provenance.source_url is None

    def test_error_names_the_methods_that_may_omit_it(self) -> None:
        """The message must tell the reader how to fix it, not just that it broke."""
        with pytest.raises(ValidationError) as exc_info:
            make_provenance(source_url=None, extraction_method=ExtractionMethod.REGEX_MATCH)
        message = str(exc_info.value)
        assert "computed" in message
        assert "merged" in message
        assert "manual_seed" in message


class TestEvidenceRequiredForExtraction:
    """The llm_extraction / llm_inference split is the core of §6's audit story."""

    def test_llm_extraction_requires_supporting_text(self) -> None:
        """A claim the model says it *read* must quote what it read."""
        with pytest.raises(ValidationError, match="evidence is required"):
            make_provenance(extraction_method=ExtractionMethod.LLM_EXTRACTION, evidence=None)

    def test_llm_extraction_rejects_empty_evidence(self) -> None:
        """An empty string is not a citation."""
        with pytest.raises(ValidationError, match="evidence is required"):
            make_provenance(extraction_method=ExtractionMethod.LLM_EXTRACTION, evidence="")

    def test_llm_inference_does_not_require_evidence(self) -> None:
        """An inferred claim has nothing on the page to quote — that is the distinction.

        Career stage is inferred from the shape of a CV, not stated on it. Demanding
        a quote here would push callers to invent one.
        """
        provenance = make_provenance(
            extraction_method=ExtractionMethod.LLM_INFERENCE, evidence=None
        )
        assert provenance.evidence is None

    @pytest.mark.parametrize(
        "method",
        [
            ExtractionMethod.MAILTO_HREF,
            ExtractionMethod.REGEX_MATCH,
            ExtractionMethod.DNS_LOOKUP,
            ExtractionMethod.COMPUTED,
        ],
    )
    def test_mechanical_methods_do_not_require_evidence(self, method: ExtractionMethod) -> None:
        """A mailto href or a DNS record is self-evidencing."""
        provenance = make_provenance(
            extraction_method=method,
            evidence=None,
            source_url=None if method is ExtractionMethod.COMPUTED else "https://x.com",
        )
        assert provenance.evidence is None


class TestConfidence:
    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_accepts_the_unit_interval(self, value: float) -> None:
        assert make_provenance(confidence=value).confidence == value

    @pytest.mark.parametrize("value", [-0.01, 1.01, 2.0, -1.0])
    def test_rejects_values_outside_zero_to_one(self, value: float) -> None:
        """Confidence feeds threshold comparisons; out-of-range silently skews them."""
        with pytest.raises(ValidationError):
            make_provenance(confidence=value)


class TestProvenanceIsImmutable:
    def test_cannot_be_mutated(self) -> None:
        """Rewriting provenance after the fact would defeat the point of recording it."""
        provenance = make_provenance()
        with pytest.raises(ValidationError, match="frozen"):
            provenance.confidence = 0.1  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            make_provenance(sourceurl="https://typo.example.com")


class TestProvenancedWrapper:
    def test_pairs_a_value_with_its_provenance(self) -> None:
        wrapped = Provenanced[str](value="Jane Doe", provenance=make_provenance())
        assert wrapped.value == "Jane Doe"
        assert wrapped.provenance.confidence == 0.9

    def test_enforces_the_type_parameter(self) -> None:
        """Provenanced[int] must not silently accept a string."""
        with pytest.raises(ValidationError):
            Provenanced[int](value="not a number", provenance=make_provenance())

    def test_wraps_composite_values(self) -> None:
        """Used for mediums, themes, and exhibition_stats on ArtistProfile."""
        wrapped = Provenanced[tuple[str, ...]](
            value=("oil painting", "mixed media"), provenance=make_provenance()
        )
        assert wrapped.value == ("oil painting", "mixed media")

    def test_provenance_is_required(self) -> None:
        """The whole point: a value cannot exist here without its origin."""
        with pytest.raises(ValidationError):
            Provenanced[str](value="Jane Doe")  # type: ignore[call-arg]

    def test_is_immutable(self) -> None:
        wrapped = Provenanced[str](value="Jane Doe", provenance=make_provenance())
        with pytest.raises(ValidationError, match="frozen"):
            wrapped.value = "Someone Else"  # type: ignore[misc]


class TestWireFormat:
    """The JSONL on disk must match the shape ARCHITECTURE.md §5 documents.

    A later run reads records written by an earlier one, so the serialized shape
    is a contract, not an implementation detail.
    """

    def test_serializes_to_value_and_provenance(self) -> None:
        wrapped = Provenanced[str](value="United Kingdom", provenance=make_provenance())
        payload = wrapped.model_dump(mode="json")
        assert set(payload) == {"value", "provenance"}
        assert payload["value"] == "United Kingdom"

    def test_provenance_carries_every_documented_key(self) -> None:
        payload = make_provenance().model_dump(mode="json")
        assert set(payload) == {
            "source_url",
            "source_type",
            "source_name",
            "extraction_method",
            "extracted_by",
            "extracted_at",
            "confidence",
            "evidence",
            "input_source_urls",
        }

    def test_enums_serialize_as_their_wire_strings(self) -> None:
        """Not as Python repr — a later run parses these back by value."""
        payload = make_provenance().model_dump(mode="json")
        assert payload["source_type"] == "artist_website"
        assert payload["extraction_method"] == "llm_extraction"

    def test_round_trips_through_json(self) -> None:
        original = Provenanced[str](value="Jane Doe", provenance=make_provenance())
        restored = Provenanced[str].model_validate_json(original.model_dump_json())
        assert restored == original

    def test_round_trip_preserves_timezone(self) -> None:
        """A timestamp that loses its offset in transit becomes ambiguous."""
        tokyo = timezone(timedelta(hours=9))
        original = make_provenance(extracted_at=datetime(2026, 7, 23, 9, tzinfo=tokyo))
        restored = Provenance.model_validate_json(original.model_dump_json())
        assert restored.extracted_at == original.extracted_at
        assert restored.extracted_at.utcoffset() == timedelta(hours=9)
