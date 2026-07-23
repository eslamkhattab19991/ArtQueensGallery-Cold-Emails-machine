"""Tests for the ArtistProfile aggregate.

Two concerns dominate: ``has_direct_contact``, which gates entry to
``qualified_leads.csv`` (ARCHITECTURE.md §4.8), and the record's ability to
represent an artist at *every* stage of the pipeline, including the many
partial states before contact discovery has run.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from prospecting.domain.enums import (
    CareerStage,
    ContactStatus,
    EmailOwnership,
    ExtractionMethod,
    Tier,
)
from prospecting.domain.identifiers import CanonicalId, RunId
from prospecting.domain.models.artist import ArtistProfile
from prospecting.domain.provenance import Provenanced
from tests.support.factories import make_email_candidate, make_provenance


def make_artist(**overrides: object) -> ArtistProfile:
    """Build a minimally valid ArtistProfile — name and id are the only requirements."""
    values: dict[str, object] = {
        "canonical_id": CanonicalId("art_8f3a2b1c"),
        "full_name": Provenanced[str](value="Jane Doe", provenance=make_provenance()),
    }
    values.update(overrides)
    return ArtistProfile(**values)


class TestHasDirectContact:
    """The single check that decides whether a lead may be exported."""

    def test_true_with_an_artist_owned_email(self) -> None:
        artist = make_artist(email=make_email_candidate(ownership=EmailOwnership.ARTIST_OWNED))
        assert artist.has_direct_contact

    def test_false_with_no_email(self) -> None:
        assert not make_artist().has_direct_contact

    def test_false_with_only_a_gallery_email(self) -> None:
        """The indirect case: qualified, reachable via a gallery, not a direct lead."""
        artist = make_artist(
            contact_status=ContactStatus.INDIRECT,
            gallery_email=make_email_candidate(
                email="info@gallery-x.com", ownership=EmailOwnership.GALLERY
            ),
        )
        assert not artist.has_direct_contact

    def test_false_when_a_gallery_address_is_misfiled_in_the_email_field(self) -> None:
        """Defence in depth against the exact bug the gallery rule targets.

        If upstream code puts a gallery address in `email` by mistake, the
        export gate must still refuse it — the check reads ownership, not which
        field the address happens to sit in.
        """
        artist = make_artist(
            email=make_email_candidate(email="info@gallery-x.com", ownership=EmailOwnership.GALLERY)
        )
        assert not artist.has_direct_contact

    @pytest.mark.parametrize(
        "ownership",
        [
            EmailOwnership.GALLERY,
            EmailOwnership.INSTITUTION,
            EmailOwnership.AGGREGATOR,
            EmailOwnership.UNKNOWN,
        ],
    )
    def test_false_for_every_non_artist_ownership(self, ownership: EmailOwnership) -> None:
        artist = make_artist(email=make_email_candidate(ownership=ownership))
        assert not artist.has_direct_contact

    def test_a_gallery_email_does_not_mask_a_real_direct_contact(self) -> None:
        """Both may be known at once; the direct address still wins."""
        artist = make_artist(
            contact_status=ContactStatus.DIRECT,
            email=make_email_candidate(ownership=EmailOwnership.ARTIST_OWNED),
            gallery_email=make_email_candidate(
                email="info@gallery-x.com", ownership=EmailOwnership.GALLERY
            ),
        )
        assert artist.has_direct_contact


class TestPartialStatesAreRepresentable:
    """The record must be constructible at every point in the pipeline.

    ARCHITECTURE.md §4: an artist exists as a record from extraction onward,
    long before qualification or contact discovery have run. Over-constraining
    the model would make those legitimate intermediate states impossible.
    """

    def test_only_id_and_name_are_required(self) -> None:
        """The state immediately after extraction."""
        artist = make_artist()
        assert artist.tier is None
        assert artist.contact_status is None
        assert artist.email is None

    def test_collections_default_to_empty(self) -> None:
        artist = make_artist()
        assert artist.exhibitions == ()
        assert artist.personalization_hooks == ()
        assert artist.source_urls == ()

    def test_qualified_but_not_yet_contacted(self) -> None:
        """Between stage 4 and stage 5."""
        artist = make_artist(
            tier=Tier.A,
            career_stage=Provenanced[CareerStage](
                value=CareerStage.MID_CAREER,
                provenance=make_provenance(
                    extraction_method=ExtractionMethod.LLM_INFERENCE, evidence=None
                ),
            ),
        )
        assert artist.tier is Tier.A
        assert artist.contact_status is None

    def test_qualified_but_unreachable(self) -> None:
        """The `exhausted` outcome: retained as an asset, retried in a later run."""
        artist = make_artist(tier=Tier.B, contact_status=ContactStatus.EXHAUSTED)
        assert not artist.has_direct_contact
        assert artist.contact_status is ContactStatus.EXHAUSTED


class TestProvenanceIsCarried:
    def test_name_carries_its_origin(self) -> None:
        artist = make_artist()
        assert artist.full_name.value == "Jane Doe"
        assert artist.full_name.provenance.source_url is not None

    def test_inferred_career_stage_is_marked_as_inference(self) -> None:
        """Career stage is concluded, not read — the method must say so."""
        artist = make_artist(
            career_stage=Provenanced[CareerStage](
                value=CareerStage.MID_CAREER,
                provenance=make_provenance(
                    extraction_method=ExtractionMethod.LLM_INFERENCE,
                    evidence=None,
                    confidence=0.86,
                ),
            )
        )
        assert artist.career_stage is not None
        assert artist.career_stage.provenance.extraction_method is (ExtractionMethod.LLM_INFERENCE)

    def test_a_bare_value_cannot_be_assigned_to_a_traced_field(self) -> None:
        """The type system is what makes forgetting provenance impossible."""
        with pytest.raises(ValidationError):
            make_artist(country="United Kingdom")


class TestCrossRunBookkeeping:
    def test_defaults_to_newly_discovered(self) -> None:
        artist = make_artist()
        assert artist.previously_known is False
        assert artist.first_seen_run is None

    def test_records_a_returning_artist(self) -> None:
        """Identity resolution updates rather than duplicates — §4.3c."""
        artist = make_artist(first_seen_run=RunId("run_2026-06-14_003"), previously_known=True)
        assert artist.previously_known is True

    def test_accumulates_every_corroborating_url(self) -> None:
        artist = make_artist(
            source_urls=(
                "https://example-artist.com",
                "https://gallery-x.com/artists/jane-doe",
            )
        )
        assert len(artist.source_urls) == 2


class TestValidation:
    def test_requires_a_name(self) -> None:
        with pytest.raises(ValidationError):
            ArtistProfile(canonical_id=CanonicalId("art_1"))  # type: ignore[call-arg]

    def test_rejects_unknown_fields(self) -> None:
        """A typo'd field must fail loudly, not be silently dropped."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            make_artist(nationalty="British")

    def test_is_immutable(self) -> None:
        """Updating means constructing a new snapshot, never mutating in place."""
        artist = make_artist()
        with pytest.raises(ValidationError, match="frozen"):
            artist.tier = Tier.A  # type: ignore[misc]


class TestSerialization:
    def test_round_trips_through_json(self) -> None:
        """A later run reads what an earlier one wrote — the shape is a contract."""
        original = make_artist(
            tier=Tier.A,
            contact_status=ContactStatus.DIRECT,
            email=make_email_candidate(),
        )
        restored = ArtistProfile.model_validate_json(original.model_dump_json())
        assert restored == original
        assert restored.has_direct_contact

    def test_enums_serialize_as_wire_strings(self) -> None:
        artist = make_artist(tier=Tier.A, contact_status=ContactStatus.DIRECT)
        payload = artist.model_dump(mode="json")
        assert payload["tier"] == "A"
        assert payload["contact_status"] == "direct"
