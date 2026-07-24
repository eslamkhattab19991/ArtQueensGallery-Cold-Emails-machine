"""Tests for the domain's controlled vocabularies.

The dominant risk with these enums is not logic but *drift*: their values are
the wire format written to JSONL and read back by a later run, so a renamed
member silently orphans every record already on disk. These tests pin the
values.
"""

from __future__ import annotations

import pytest

from prospecting.domain.enums import (
    CareerStage,
    ContactMethod,
    ContactStatus,
    EmailOwnership,
    ExhibitionType,
    ExtractionMethod,
    RejectReason,
    SourceTier,
    SourceType,
    Tier,
)

ALL_ENUMS = [
    CareerStage,
    ContactMethod,
    ContactStatus,
    EmailOwnership,
    ExhibitionType,
    ExtractionMethod,
    RejectReason,
    SourceTier,
    SourceType,
    Tier,
]


class TestWireValuesArePinned:
    """Renaming a Python identifier must never change what is on disk."""

    def test_career_stage_values(self) -> None:
        assert {stage.value for stage in CareerStage} == {
            "student",
            "hobbyist",
            "recent_graduate",
            "emerging",
            "mid_career",
            "established",
            "celebrity",
        }

    def test_contact_status_values(self) -> None:
        assert {status.value for status in ContactStatus} == {
            "direct",
            "indirect",
            "exhausted",
        }

    def test_email_ownership_values(self) -> None:
        assert {ownership.value for ownership in EmailOwnership} == {
            "artist_owned",
            "gallery",
            "institution",
            "aggregator",
            "unknown",
        }

    def test_extraction_method_values(self) -> None:
        assert {method.value for method in ExtractionMethod} == {
            "mailto_href",
            "regex_match",
            "structured_parse",
            "dns_lookup",
            "llm_extraction",
            "llm_inference",
            "llm_synthesis",
            "computed",
            "merged",
            "manual_seed",
        }

    def test_source_tier_values_are_uppercase(self) -> None:
        """ARCHITECTURE.md §4.5.2 shows these uppercase in the event stream."""
        assert {tier.value for tier in SourceTier} == {
            "CACHED",
            "CHEAP",
            "MODERATE",
            "EXPENSIVE",
        }

    def test_tier_values(self) -> None:
        assert {tier.value for tier in Tier} == {"A", "B", "C"}

    def test_contact_method_values(self) -> None:
        assert {method.value for method in ContactMethod} == {
            "email",
            "phone",
            "form",
            "social_handle",
        }


class TestOnlyEmailCanCompleteALead:
    """ARCHITECTURE.md §0: completion requires a verified email, nothing else.

    The other contact methods are enrichment. Pinning this as a test guards the
    business contract against a future change that quietly treats a phone number
    or contact form as a completion channel.
    """

    #: The channels that are useful for outreach but can never complete a lead.
    ENRICHMENT_CHANNELS = {
        ContactMethod.PHONE,
        ContactMethod.FORM,
        ContactMethod.SOCIAL_HANDLE,
    }

    def test_email_is_a_contact_method(self) -> None:
        assert ContactMethod.EMAIL.value == "email"

    def test_email_is_not_one_of_the_enrichment_channels(self) -> None:
        assert ContactMethod.EMAIL not in self.ENRICHMENT_CHANNELS

    def test_email_and_the_enrichment_channels_partition_the_enum(self) -> None:
        """Every member is either the completion channel or an enrichment one."""
        assert {ContactMethod.EMAIL, *self.ENRICHMENT_CHANNELS} == set(ContactMethod)


class TestTierExcludesRejection:
    """A rejected artist has no tier — it has a RejectReason.

    ARCHITECTURE.md §4.4 lists "reject" in its threshold table, but a rejected
    lead never reaches outreach. Keeping Tier to the three qualifying values is
    what makes "has a tier" mean "qualified", which the export stage relies on.
    """

    def test_has_exactly_three_members(self) -> None:
        assert len(Tier) == 3

    def test_has_no_reject_member(self) -> None:
        assert "reject" not in {tier.value.lower() for tier in Tier}

    def test_rejection_is_expressed_as_a_reason_instead(self) -> None:
        assert RejectReason.SCORE_BELOW_THRESHOLD.value == "score_below_threshold"


class TestRejectReasonCoversTheHardFilters:
    """One reason per hard filter in ARCHITECTURE.md §4.4, plus score rejection."""

    def test_covers_every_hard_filter(self) -> None:
        assert {reason.value for reason in RejectReason} == {
            "gender_not_confirmed_female",
            "outside_priority_geography",
            "missing_full_name",
            "suppressed",
            "score_below_threshold",
        }

    def test_email_presence_is_not_a_rejection_reason(self) -> None:
        """Email presence is not a qualification concern.

        Revision 2 removed it: reachability is contact discovery's problem, not
        qualification's. A qualified but unreachable artist stays in the database.
        """
        assert not any("email" in reason.value for reason in RejectReason)

    def test_career_stage_is_not_a_rejection_reason(self) -> None:
        """Career stage is a scored signal, not a hard filter.

        A student or celebrity is rejected via SCORE_BELOW_THRESHOLD rather than
        a dedicated reason.
        """
        assert not any("career" in reason.value for reason in RejectReason)


class TestExhibitionTypeMatchesTheStatsItFeeds:
    def test_covers_every_counted_category(self) -> None:
        """ARCHITECTURE.md §4.7's exhibition_stats counts exactly these."""
        assert {exhibition_type.value for exhibition_type in ExhibitionType} == {
            "solo",
            "group",
            "museum",
            "biennial",
            "art_fair",
        }


class TestSourceTypeCoversTheDocumentedSources:
    def test_values(self) -> None:
        assert {source.value for source in SourceType} == {
            "artist_website",
            "gallery_website",
            "search_result",
            "directory",
            "social",
            "pdf_document",
            "evidence_platform",
            "derived",
        }


class TestStringEnumBehaviour:
    @pytest.mark.parametrize("enum_class", ALL_ENUMS)
    def test_members_compare_equal_to_their_wire_string(
        self, enum_class: type[CareerStage]
    ) -> None:
        """StrEnum means a member reads back from JSON without manual coercion."""
        for member in enum_class:
            assert member == member.value

    @pytest.mark.parametrize("enum_class", ALL_ENUMS)
    def test_values_are_unique(self, enum_class: type[CareerStage]) -> None:
        """Two members sharing a value would make records ambiguous on read-back."""
        values = [member.value for member in enum_class]
        assert len(values) == len(set(values))

    @pytest.mark.parametrize("enum_class", ALL_ENUMS)
    def test_can_be_reconstructed_from_its_value(self, enum_class: type[CareerStage]) -> None:
        for member in enum_class:
            assert enum_class(member.value) is member
