"""The input contract: one art-world organization from the seed sheet.

These are **discovery surfaces**, not leads. Each row names an organization that
presents artists; the pipeline crawls it to find the artists, and the
organization itself is never a prospect.

Every rule below was derived from reading all 192 rows of the real
``Galleries sheet.xlsx`` during the roster-probe spike, not assumed in advance.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from prospecting.domain.base import FrozenModel

__all__ = ["MISSING_WEBSITE_SENTINEL", "OrganizationType", "SeedOrganization"]

#: The sheet writes this literal string where a website is unknown. 19 of 192
#: rows carry it. It must never be treated as a URL.
MISSING_WEBSITE_SENTINEL = "not found"

_INSTAGRAM_HANDLE = re.compile(r"^@[A-Za-z0-9._]{1,30}$")


class OrganizationType(StrEnum):
    """What kind of organization a seed row names.

    Despite the sheet's filename, the rows are **not** homogeneous galleries.
    The spike found at least five distinct kinds mixed together, and each
    presents artists differently — a gallery has a roster, a prize has winners
    and a shortlist, a magazine has featured-artist articles. Stage 2 routes its
    crawl strategy on this value, which is why it is a closed enum rather than a
    free string.

    :attr:`SUPPLIER` exists because the sheet contains at least one organization
    with no artist roster at all (Raymar Panels, a paint-panel manufacturer).
    Modelling that explicitly is cheaper than repeatedly crawling a site that
    can never yield an artist.
    """

    GALLERY = "gallery"
    PRIZE = "prize"
    MAGAZINE = "magazine"
    MUSEUM = "museum"
    FOUNDATION = "foundation"
    ART_SPACE = "art_space"
    SUPPLIER = "supplier"
    UNKNOWN = "unknown"

    @property
    def is_likely_to_have_a_roster(self) -> bool:
        """Whether this kind of organization normally lists artists.

        Used to order the discovery queue, never to skip a row outright: the
        keyword classification that assigns this type is a guess from the
        organization's name, and the spike showed it is wrong often enough
        (99 of 192 rows landed in ``UNKNOWN``) that treating it as authoritative
        would discard real rosters. ``UNKNOWN`` therefore returns ``True``.
        """
        return self is not OrganizationType.SUPPLIER


class SeedOrganization(FrozenModel):
    """One row of the seed sheet, normalized.

    Carries no provenance wrapper, unlike the domain models: a seed row is an
    operator-supplied input, not a claim extracted from a page. Its provenance
    is the sheet itself, recorded once per run rather than per field.
    """

    row_number: int = Field(ge=2, description="1-based row in the sheet; row 1 is the header.")
    name: str = Field(min_length=1, description="Organization name as written in the sheet.")
    instagram: str | None = Field(default=None, description="Handle including the leading '@'.")
    website: str | None = Field(
        default=None, description="Homepage URL, or None where the sheet said 'Not found'."
    )
    organization_type: OrganizationType = Field(default=OrganizationType.UNKNOWN)

    @field_validator("name", "instagram", "website", mode="before")
    @classmethod
    def _strip_whitespace(cls, value: object) -> object:
        """Trim surrounding whitespace before any other check sees the value."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("website", mode="before")
    @classmethod
    def _sentinel_means_absent(cls, value: object) -> object:
        """Convert the sheet's "Not found" placeholder into a real absence.

        Left as a string it would be treated as a URL and crawled, producing 19
        guaranteed failures per run and polluting the error rate with a problem
        that is not an error at all.
        """
        if isinstance(value, str) and value.strip().lower() == MISSING_WEBSITE_SENTINEL:
            return None
        return value

    @field_validator("website")
    @classmethod
    def _website_must_be_http(cls, value: str | None) -> str | None:
        """Reject anything that is not an http(s) URL."""
        if value is None:
            return None
        if not value.lower().startswith(("http://", "https://")):
            message = (
                f"website must be an http(s) URL, got {value!r}. "
                f"Absent websites are written as {MISSING_WEBSITE_SENTINEL!r} in the sheet."
            )
            raise ValueError(message)
        return value

    @field_validator("instagram")
    @classmethod
    def _instagram_must_be_a_handle(cls, value: str | None) -> str | None:
        """Require the '@handle' form the sheet uses throughout.

        All 192 rows use it. Accepting a bare handle or a profile URL here would
        mean every downstream consumer has to normalize defensively.
        """
        if value is None:
            return None
        if not _INSTAGRAM_HANDLE.match(value):
            message = (
                f"instagram must look like '@handle', got {value!r}. "
                "Convert a profile URL to its handle before constructing the seed."
            )
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def _must_be_reachable_somehow(self) -> Self:
        """Require at least one way to reach the organization.

        A row with neither a website nor an Instagram handle cannot be crawled
        by any discovery surface, so it is not a seed — it is a typo.
        """
        if self.website is None and self.instagram is None:
            message = (
                f"Row {self.row_number} ({self.name!r}) has neither a website nor an "
                "Instagram handle, so no discovery surface can reach it."
            )
            raise ValueError(message)
        return self

    @property
    def is_instagram_only(self) -> bool:
        """Whether this organization can only be reached through Instagram.

        19 of the 192 seed rows. They need a different discovery path from
        website-bearing organizations, and counting them separately keeps the
        run report honest about what was actually crawlable.
        """
        return self.website is None and self.instagram is not None
