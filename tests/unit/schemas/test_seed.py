"""Tests for the seed-organization input contract.

Every rule here was derived from the real ``Galleries sheet.xlsx`` during the
roster-probe spike. The final test class validates the schema against that
actual file, so a change to the sheet's conventions fails the suite rather than
the next pipeline run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from prospecting.schemas.seed import (
    MISSING_WEBSITE_SENTINEL,
    OrganizationType,
    SeedOrganization,
)


def make_seed(**overrides: object) -> SeedOrganization:
    values: dict[str, object] = {
        "row_number": 2,
        "name": "Maya Galerie Wien",
        "instagram": "@mayagalerie_wien",
        "website": "https://maya-galerie.at/",
    }
    values.update(overrides)
    return SeedOrganization(**values)


class TestMissingWebsiteSentinel:
    """19 of 192 rows write "Not found" instead of a URL."""

    def test_sentinel_becomes_none(self) -> None:
        assert make_seed(website="Not found").website is None

    @pytest.mark.parametrize("variant", ["Not found", "not found", "NOT FOUND", "  Not Found  "])
    def test_sentinel_matching_ignores_case_and_padding(self, variant: str) -> None:
        assert make_seed(website=variant).website is None

    def test_a_row_with_the_sentinel_is_instagram_only(self) -> None:
        assert make_seed(website="Not found").is_instagram_only

    def test_a_row_with_a_website_is_not_instagram_only(self) -> None:
        assert not make_seed().is_instagram_only

    def test_the_sentinel_constant_matches_the_sheet(self) -> None:
        assert MISSING_WEBSITE_SENTINEL == "not found"


class TestWebsiteValidation:
    @pytest.mark.parametrize("url", ["https://maya-galerie.at/", "http://example.com"])
    def test_accepts_http_urls(self, url: str) -> None:
        assert make_seed(website=url).website == url

    @pytest.mark.parametrize("bad", ["maya-galerie.at", "www.example.com", "ftp://x.com"])
    def test_rejects_anything_that_is_not_http(self, bad: str) -> None:
        with pytest.raises(ValidationError, match="http"):
            make_seed(website=bad)

    def test_strips_surrounding_whitespace(self) -> None:
        assert make_seed(website="  https://example.com  ").website == "https://example.com"


class TestInstagramValidation:
    def test_accepts_the_at_handle_form(self) -> None:
        assert make_seed(instagram="@artists.collectors").instagram == "@artists.collectors"

    def test_accepts_handles_with_dots_and_underscores(self) -> None:
        """Both appear throughout the real sheet."""
        assert make_seed(instagram="@galerie_c.o.a").instagram == "@galerie_c.o.a"

    @pytest.mark.parametrize(
        "bad",
        ["mayagalerie", "https://instagram.com/maya", "@", "@has spaces"],
    )
    def test_rejects_non_handle_forms(self, bad: str) -> None:
        """Normalizing defensively downstream is worse than rejecting once here."""
        with pytest.raises(ValidationError, match="@handle"):
            make_seed(instagram=bad)


class TestReachability:
    def test_website_alone_is_enough(self) -> None:
        assert make_seed(instagram=None).website is not None

    def test_instagram_alone_is_enough(self) -> None:
        assert make_seed(website=None).is_instagram_only

    def test_a_row_with_neither_is_rejected(self) -> None:
        """No discovery surface can reach it, so it is a typo, not a seed."""
        with pytest.raises(ValidationError, match="neither a website nor an"):
            make_seed(website=None, instagram=None)

    def test_the_error_names_the_offending_row(self) -> None:
        """192 rows: a message without the row number is not actionable."""
        with pytest.raises(ValidationError, match="Row 57"):
            make_seed(row_number=57, website=None, instagram=None)


class TestOrganizationType:
    def test_defaults_to_unknown(self) -> None:
        """99 of 192 rows carry no type keyword in their name."""
        assert make_seed().organization_type is OrganizationType.UNKNOWN

    def test_suppliers_are_not_expected_to_have_rosters(self) -> None:
        """Raymar Panels sells paint panels; it will never list an artist."""
        assert not OrganizationType.SUPPLIER.is_likely_to_have_a_roster

    @pytest.mark.parametrize(
        "org_type",
        [
            OrganizationType.GALLERY,
            OrganizationType.PRIZE,
            OrganizationType.MAGAZINE,
            OrganizationType.MUSEUM,
            OrganizationType.FOUNDATION,
            OrganizationType.ART_SPACE,
        ],
    )
    def test_artist_presenting_types_are_expected_to_have_rosters(
        self, org_type: OrganizationType
    ) -> None:
        assert org_type.is_likely_to_have_a_roster

    def test_unknown_is_treated_as_possibly_having_a_roster(self) -> None:
        """Treat an unclassified organization as possibly having a roster.

        The classifier guesses from the name and is wrong often enough that
        treating UNKNOWN as barren would discard real rosters — the spike found
        rich rosters behind names like "TERAVARNA" and "Art Loving".
        """
        assert OrganizationType.UNKNOWN.is_likely_to_have_a_roster


class TestImmutabilityAndStrictness:
    def test_is_immutable(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            make_seed().name = "Something Else"  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            make_seed(instgram="@typo")

    def test_requires_a_name(self) -> None:
        with pytest.raises(ValidationError):
            make_seed(name="")

    def test_rejects_the_header_row(self) -> None:
        """Row 1 is the header; a seed constructed from it is a parsing bug."""
        with pytest.raises(ValidationError):
            make_seed(row_number=1)


class TestAgainstTheRealSheet:
    """Validate the contract against the actual input file.

    The schema exists to describe *this* sheet. If its conventions change — a
    new sentinel, a bare handle, a renamed column — that must fail here rather
    than midway through a paid run.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def sheet_rows(cls, project_root: Path) -> list[tuple[object, ...]]:
        openpyxl = pytest.importorskip(
            "openpyxl", reason="openpyxl arrives with the ingestion adapter"
        )
        workbook_path = project_root / "Galleries sheet.xlsx"
        if not workbook_path.is_file():
            pytest.skip("Galleries sheet.xlsx is not present in this checkout")
        workbook = openpyxl.load_workbook(workbook_path, data_only=True)
        sheet = workbook["Collected Accounts"]
        return list(sheet.iter_rows(min_row=2, values_only=True))

    def test_every_row_satisfies_the_contract(self, sheet_rows: list[tuple[object, ...]]) -> None:
        failures: list[str] = []
        for index, row in enumerate(sheet_rows, start=2):
            name, instagram, website = (str(cell).strip() if cell else "" for cell in row[:3])
            if not name:
                continue
            try:
                SeedOrganization(
                    row_number=index,
                    name=name,
                    instagram=instagram or None,
                    website=website or None,
                )
            except ValidationError as exc:
                failures.append(f"row {index} ({name}): {exc.errors()[0]['msg']}")

        assert not failures, "Rows the schema rejects:\n" + "\n".join(failures)

    def test_the_expected_number_of_rows_is_instagram_only(
        self, sheet_rows: list[tuple[object, ...]]
    ) -> None:
        """Expect the 19 Instagram-only rows the spike counted.

        A change means the sheet was edited — worth noticing deliberately rather
        than discovering through a shifted crawl count mid-run.
        """
        seeds = [
            SeedOrganization(
                row_number=index,
                name=str(row[0]).strip(),
                instagram=str(row[1]).strip() if row[1] else None,
                website=str(row[2]).strip() if row[2] else None,
            )
            for index, row in enumerate(sheet_rows, start=2)
            if row[0]
        ]
        assert len(seeds) == 192
        assert sum(1 for seed in seeds if seed.is_instagram_only) == 19
