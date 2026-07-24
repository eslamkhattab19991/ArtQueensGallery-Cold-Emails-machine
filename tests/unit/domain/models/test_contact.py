"""Tests for EmailCandidate and the ownership rule.

Revision 3 of ARCHITECTURE.md added an explicit business rule: a gallery address
is never a successful artist contact (§4.5.5, §4.8). ``is_directly_contactable``
is where that rule is decided, so every ownership class is tested against it —
not just the two obvious ones.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from prospecting.domain.enums import EmailOwnership, ExtractionMethod, SourceType
from prospecting.domain.models.contact import EmailCandidate, PhoneCandidate
from tests.support.factories import (
    make_email_candidate,
    make_phone_candidate,
    make_provenance,
)

#: Every ownership class that must NOT count as a direct artist contact.
NON_ARTIST_OWNERSHIP = [
    EmailOwnership.GALLERY,
    EmailOwnership.INSTITUTION,
    EmailOwnership.AGGREGATOR,
    EmailOwnership.UNKNOWN,
]


class TestOwnershipGatesDirectContact:
    def test_artist_owned_is_directly_contactable(self) -> None:
        candidate = make_email_candidate(ownership=EmailOwnership.ARTIST_OWNED)
        assert candidate.is_directly_contactable

    @pytest.mark.parametrize("ownership", NON_ARTIST_OWNERSHIP)
    def test_every_other_ownership_is_not(self, ownership: EmailOwnership) -> None:
        """Including UNKNOWN: an unclassified address must never be assumed safe.

        Defaulting the ambiguous case to "contactable" is how a gallery address
        would leak into qualified_leads.csv.
        """
        candidate = make_email_candidate(ownership=ownership)
        assert not candidate.is_directly_contactable

    def test_exactly_one_ownership_class_qualifies(self) -> None:
        """Guards against a future enum member silently becoming contactable."""
        contactable = [
            ownership
            for ownership in EmailOwnership
            if make_email_candidate(ownership=ownership).is_directly_contactable
        ]
        assert contactable == [EmailOwnership.ARTIST_OWNED]


class TestOwnershipIsIndependentOfSource:
    """ARCHITECTURE.md §4.5.4: ownership is classified per candidate, not per source.

    A gallery contact page routinely surfaces from a plain web search for an
    artist's name. If ownership were inferred from which source found the
    address, that case would be misfiled as a direct contact — which is exactly
    the failure the rule exists to prevent.
    """

    def test_a_gallery_address_found_by_web_search_is_still_a_gallery_address(
        self,
    ) -> None:
        candidate = make_email_candidate(
            email="info@gallery-x.com",
            ownership=EmailOwnership.GALLERY,
            provenance=make_provenance(
                source_type=SourceType.SEARCH_RESULT,
                source_name="open_web_search",
                extraction_method=ExtractionMethod.REGEX_MATCH,
                evidence=None,
            ),
        )
        assert not candidate.is_directly_contactable

    def test_an_artist_address_found_on_a_gallery_page_is_still_the_artists(self) -> None:
        """The mirror case: the source is a gallery site, the address is not."""
        candidate = make_email_candidate(
            email="jane@example-artist.com",
            ownership=EmailOwnership.ARTIST_OWNED,
            provenance=make_provenance(
                source_type=SourceType.GALLERY_WEBSITE,
                source_name="gallery_page",
                extraction_method=ExtractionMethod.MAILTO_HREF,
                evidence=None,
            ),
        )
        assert candidate.is_directly_contactable


class TestCorroboration:
    """Agreement across independent sources is what raises confidence (§4.5.3)."""

    def test_defaults_to_no_corroboration(self) -> None:
        assert make_email_candidate().corroborating_provenance == ()

    def test_records_each_confirming_source(self) -> None:
        candidate = make_email_candidate(
            corroborating_provenance=(
                make_provenance(source_url="https://artfacts.net/artist/jane-doe"),
                make_provenance(source_url="https://gallery-x.com/artists/jane-doe"),
            )
        )
        assert len(candidate.corroborating_provenance) == 2

    def test_primary_provenance_stays_distinct_from_corroborating(self) -> None:
        """The finding source and the confirming sources must not be conflated."""
        primary = make_provenance(source_url="https://example-artist.com/contact")
        candidate = make_email_candidate(
            provenance=primary,
            corroborating_provenance=(
                make_provenance(source_url="https://artfacts.net/artist/jane-doe"),
            ),
        )
        assert candidate.provenance.source_url == "https://example-artist.com/contact"
        assert primary not in candidate.corroborating_provenance


class TestValidation:
    def test_requires_provenance(self) -> None:
        """An address with no traceable origin cannot be acted on or defended."""
        with pytest.raises(ValidationError):
            EmailCandidate(  # type: ignore[call-arg]
                email="jane@example-artist.com", ownership=EmailOwnership.ARTIST_OWNED
            )

    def test_rejects_an_empty_address(self) -> None:
        with pytest.raises(ValidationError):
            make_email_candidate(email="")

    def test_is_immutable(self) -> None:
        """Ownership must not be reassignable after classification."""
        candidate = make_email_candidate()
        with pytest.raises(ValidationError, match="frozen"):
            candidate.ownership = EmailOwnership.GALLERY  # type: ignore[misc]


class TestPhoneCandidateIsEnrichmentOnly:
    """A phone number is a follow-up channel, never a completion key.

    ARCHITECTURE.md §0: a lead completes on a verified email and nothing else.
    ``PhoneCandidate`` therefore deliberately has no ``ownership`` field and no
    ``is_directly_contactable`` gate — the ownership machinery exists to protect
    the completion KPI, and a phone number cannot reach it.
    """

    def test_carries_no_ownership_gate(self) -> None:
        """The absence is the design: phone cannot be mistaken for a lead key."""
        assert not hasattr(make_phone_candidate(), "ownership")
        assert not hasattr(make_phone_candidate(), "is_directly_contactable")

    def test_stores_the_number_as_found(self) -> None:
        candidate = make_phone_candidate(number="+33 1 42 60 30 30")
        assert candidate.number == "+33 1 42 60 30 30"

    def test_requires_provenance(self) -> None:
        """A number with no traceable origin cannot be defended under GDPR."""
        with pytest.raises(ValidationError):
            PhoneCandidate(number="+44 20 7946 0958")  # type: ignore[call-arg]

    def test_rejects_an_empty_number(self) -> None:
        with pytest.raises(ValidationError):
            make_phone_candidate(number="")

    def test_defaults_to_no_corroboration(self) -> None:
        assert make_phone_candidate().corroborating_provenance == ()

    def test_records_each_confirming_source(self) -> None:
        candidate = make_phone_candidate(
            corroborating_provenance=(
                make_provenance(source_url="https://example-artist.com/imprint"),
            )
        )
        assert len(candidate.corroborating_provenance) == 1

    def test_is_immutable(self) -> None:
        candidate = make_phone_candidate()
        with pytest.raises(ValidationError, match="frozen"):
            candidate.number = "+1 202 555 0143"  # type: ignore[misc]
