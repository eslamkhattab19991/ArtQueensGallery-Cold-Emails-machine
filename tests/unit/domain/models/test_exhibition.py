"""Tests for Exhibition and the statistics computed from a set of them.

ExhibitionStats feeds the highest-weighted qualification signal (30 points for
exhibition history, ARCHITECTURE.md §4.4) and the career-stage inference that
gates the whole ICP. A miscount here does not fail loudly — it quietly moves
artists between tiers.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from prospecting.domain.enums import ExhibitionType
from prospecting.domain.models.exhibition import Exhibition, ExhibitionStats
from tests.support.factories import make_provenance

UK = "United Kingdom"


def make_exhibition(**overrides: object) -> Exhibition:
    """Build a valid Exhibition, overriding only what a test cares about."""
    values: dict[str, object] = {
        "year": 2024,
        "title": "Interior Weather",
        "venue": "Gallery X",
        "city": "London",
        "country": UK,
        "type": ExhibitionType.SOLO,
        "provenance": make_provenance(),
    }
    values.update(overrides)
    return Exhibition(**values)


class TestExhibition:
    def test_title_is_optional(self) -> None:
        """Group shows and fair appearances are often listed without a title."""
        assert make_exhibition(title=None).title is None

    def test_requires_a_venue(self) -> None:
        with pytest.raises(ValidationError):
            make_exhibition(venue="")

    @pytest.mark.parametrize("year", [1899, 2101])
    def test_rejects_implausible_years(self, year: int) -> None:
        """Guards against a parse that grabbed a street number or a price."""
        with pytest.raises(ValidationError):
            make_exhibition(year=year)

    def test_carries_provenance(self) -> None:
        assert make_exhibition().provenance.source_url is not None

    def test_is_immutable(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            make_exhibition().year = 2020  # type: ignore[misc]


class TestStatsWithNoHistory:
    """An artist with no discovered exhibitions must produce zeros, not crash."""

    def test_all_counts_are_zero(self) -> None:
        stats = ExhibitionStats.from_exhibitions((), home_country=UK)
        assert stats.total == 0
        assert stats.solo == 0
        assert stats.international_count == 0

    def test_years_are_none_and_span_is_zero(self) -> None:
        """None means "unknown"; 0 span is the honest arithmetic answer."""
        stats = ExhibitionStats.from_exhibitions((), home_country=UK)
        assert stats.first_year is None
        assert stats.latest_year is None
        assert stats.span_years == 0


class TestCountingByType:
    def test_counts_each_type_separately(self) -> None:
        exhibitions = (
            make_exhibition(type=ExhibitionType.SOLO),
            make_exhibition(type=ExhibitionType.SOLO),
            make_exhibition(type=ExhibitionType.GROUP),
            make_exhibition(type=ExhibitionType.MUSEUM),
            make_exhibition(type=ExhibitionType.BIENNIAL),
            make_exhibition(type=ExhibitionType.ART_FAIR),
        )
        stats = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        assert stats.total == 6
        assert stats.solo == 2
        assert stats.group == 1
        assert stats.museum == 1
        assert stats.biennial == 1
        assert stats.art_fair == 1

    def test_per_type_counts_sum_to_the_total(self) -> None:
        """The categories partition the set; a gap would mean a lost exhibition."""
        exhibitions = tuple(
            make_exhibition(type=exhibition_type) for exhibition_type in ExhibitionType
        )
        stats = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        assert (
            stats.solo + stats.group + stats.museum + stats.biennial + stats.art_fair == stats.total
        )

    def test_absent_types_count_zero(self) -> None:
        stats = ExhibitionStats.from_exhibitions(
            (make_exhibition(type=ExhibitionType.SOLO),), home_country=UK
        )
        assert stats.biennial == 0


class TestSpanCalculation:
    """Span is the strongest single indicator of career stage."""

    def test_span_is_latest_minus_first(self) -> None:
        exhibitions = (
            make_exhibition(year=2011),
            make_exhibition(year=2018),
            make_exhibition(year=2024),
        )
        stats = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        assert stats.first_year == 2011
        assert stats.latest_year == 2024
        assert stats.span_years == 13

    def test_a_single_exhibition_spans_zero_years(self) -> None:
        stats = ExhibitionStats.from_exhibitions((make_exhibition(year=2024),), home_country=UK)
        assert stats.first_year == stats.latest_year == 2024
        assert stats.span_years == 0

    def test_input_order_does_not_matter(self) -> None:
        """CVs list newest-first as often as oldest-first."""
        ascending = (make_exhibition(year=2011), make_exhibition(year=2024))
        descending = tuple(reversed(ascending))
        assert ExhibitionStats.from_exhibitions(
            ascending, home_country=UK
        ) == ExhibitionStats.from_exhibitions(descending, home_country=UK)

    def test_several_exhibitions_in_one_year(self) -> None:
        exhibitions = (make_exhibition(year=2024), make_exhibition(year=2024))
        stats = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        assert stats.total == 2
        assert stats.span_years == 0


class TestInternationalCount:
    """International reach is evidence an artist already travels to exhibit."""

    def test_counts_exhibitions_outside_the_home_country(self) -> None:
        exhibitions = (
            make_exhibition(country=UK),
            make_exhibition(country="France"),
            make_exhibition(country="Italy"),
        )
        stats = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        assert stats.international_count == 2

    def test_domestic_only_history_counts_zero(self) -> None:
        exhibitions = (make_exhibition(country=UK), make_exhibition(country=UK))
        stats = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        assert stats.international_count == 0

    def test_unknown_home_country_yields_zero_not_a_guess(self) -> None:
        """Treat an unknown home country as zero international, not as a guess.

        Not knowing where an artist lives is not evidence that every show was
        abroad. Counting them all international would inflate the strongest
        signal in the rubric on exactly the artists we know least about.
        """
        exhibitions = (
            make_exhibition(country=UK),
            make_exhibition(country="France"),
        )
        stats = ExhibitionStats.from_exhibitions(exhibitions, home_country=None)
        assert stats.international_count == 0


class TestStatsAreDeterministic:
    def test_same_input_gives_an_equal_result(self) -> None:
        """Computed, never asserted by a model — so it must be reproducible."""
        exhibitions = (
            make_exhibition(year=2011, type=ExhibitionType.GROUP),
            make_exhibition(year=2024, country="France"),
        )
        first = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        second = ExhibitionStats.from_exhibitions(exhibitions, home_country=UK)
        assert first == second
