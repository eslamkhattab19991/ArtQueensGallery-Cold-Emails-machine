"""Ideal Artist Profile: the tunable definition of a qualified lead."""

from __future__ import annotations

import re

from pydantic import Field, field_validator, model_validator

from prospecting.config.models.base import FrozenConfig

__all__ = ["IcpConfig", "SignalWeights", "TierThresholds"]

#: ISO 3166-1 alpha-2: exactly two uppercase letters.
_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")

#: Weights are expressed as points out of this total, matching ARCHITECTURE.md §4.4.
WEIGHT_TOTAL = 100.0

#: Floating-point comparison tolerance for the weight-sum rule.
_WEIGHT_TOLERANCE = 1e-9


class SignalWeights(FrozenConfig):
    """Relative importance of each scored qualification signal.

    Fields are explicit rather than a free-form mapping. A new signal needs
    scoring logic as well as a weight, so adding one should be a deliberate
    change in both code and configuration — not something a YAML edit can
    introduce silently. It also keeps signal names out of the code as literals.

    Weights come from ARCHITECTURE.md §4.4 and must total
    :data:`WEIGHT_TOTAL`; see :meth:`_must_total_one_hundred`.
    """

    exhibition_history: float = Field(ge=0.0, description="Depth and span of exhibition record.")
    career_stage_fit: float = Field(ge=0.0, description="Fit to the mid-career/established band.")
    professional_presence: float = Field(
        ge=0.0, description="Quality of online professional presence."
    )
    gallery_representation: float = Field(
        ge=0.0, description="Breadth and standing of representation."
    )
    english_fluency: float = Field(ge=0.0, description="Ability to engage with English outreach.")
    personalization_potential: float = Field(
        ge=0.0, description="Whether enough material exists to write a specific email."
    )

    @model_validator(mode="after")
    def _must_total_one_hundred(self) -> SignalWeights:
        """Reject weights that do not sum to :data:`WEIGHT_TOTAL`.

        Without this rule, editing one weight silently rescales every score and
        invalidates the tier thresholds — a change that produces plausible-looking
        numbers and would likely be noticed only after a bad outreach batch.
        """
        total = sum(self.as_mapping().values())
        if abs(total - WEIGHT_TOTAL) > _WEIGHT_TOLERANCE:
            message = (
                f"Signal weights must sum to {WEIGHT_TOTAL:g}, got {total:g}. "
                "Scores are reported on a 0-100 scale and tier thresholds assume that scale."
            )
            raise ValueError(message)
        return self

    def as_mapping(self) -> dict[str, float]:
        """Return the weights keyed by signal name, for scoring and reporting."""
        return self.model_dump()


class TierThresholds(FrozenConfig):
    """Minimum total score for each outreach tier.

    A lead scoring below ``tier_c`` is rejected. Thresholds are exclusive lower
    bounds on the tier below them, so they must strictly descend.
    """

    tier_a: float = Field(ge=0.0, le=100.0, description="Minimum score for tier A.")
    tier_b: float = Field(ge=0.0, le=100.0, description="Minimum score for tier B.")
    tier_c: float = Field(
        ge=0.0, le=100.0, description="Minimum score for tier C; below this, reject."
    )

    @model_validator(mode="after")
    def _must_strictly_descend(self) -> TierThresholds:
        """Reject thresholds that overlap or invert, which would make a tier unreachable."""
        if not self.tier_a > self.tier_b > self.tier_c:
            message = (
                f"Tier thresholds must strictly descend, got "
                f"A={self.tier_a:g}, B={self.tier_b:g}, C={self.tier_c:g}. "
                "Equal or inverted thresholds leave at least one tier unreachable."
            )
            raise ValueError(message)
        return self


class IcpConfig(FrozenConfig):
    """The tunable definition of a qualified artist.

    Everything here is expected to change as outreach data accumulates, which is
    precisely why none of it lives in code. ``rubric_version`` is stamped onto
    every scored record so that a lead's score can always be traced to the
    ruleset that produced it — a score is not comparable across rubric versions.

    Career-stage targeting is intentionally absent at this phase: it is
    expressed in terms of the ``CareerStage`` enum, which belongs to the domain
    layer (Phase 3). Adding it here as loose strings now would mean rewriting it
    once the enum exists.
    """

    rubric_version: str = Field(
        min_length=1, description="Identifier stamped onto every score for traceability."
    )
    priority_countries: frozenset[str] = Field(
        min_length=1, description="ISO 3166-1 alpha-2 codes for in-scope countries."
    )
    allow_other_high_income_countries: bool = Field(
        description="Whether high-income countries outside the priority list may qualify."
    )
    min_gender_confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence floor for the female-artist hard filter."
    )
    min_field_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence floor below which an extracted field is not trusted.",
    )
    signal_weights: SignalWeights = Field(description="Relative importance of each scored signal.")
    tier_thresholds: TierThresholds = Field(description="Score boundaries between outreach tiers.")

    @field_validator("priority_countries", mode="before")
    @classmethod
    def _reject_yaml_coerced_country_codes(cls, value: object) -> object:
        """Detect country codes that YAML silently turned into booleans.

        YAML 1.1 resolves the unquoted token ``NO`` to ``false`` — the "Norway
        problem". Left to the default type error, this surfaces as "Input should
        be a valid string" against a list index, which does not tell the reader
        that their country code was eaten by the parser. Naming the cause here
        turns a puzzling failure into a one-line fix.
        """
        if not isinstance(value, list | set | frozenset | tuple):
            return value

        coerced = [entry for entry in value if isinstance(entry, bool)]
        if coerced:
            message = (
                "Country code was parsed as a boolean by YAML, not as text. "
                "This happens to unquoted NO (Norway), which YAML 1.1 reads as false. "
                'Quote the codes in config/icp.yaml, e.g. - "NO".'
            )
            raise ValueError(message)
        return value

    @field_validator("priority_countries")
    @classmethod
    def _must_be_iso_alpha2(cls, value: frozenset[str]) -> frozenset[str]:
        """Reject anything that is not an uppercase two-letter country code.

        Country names ("United Kingdom") and lowercase codes ("gb") would fail
        to match extracted values and silently exclude an entire market.
        """
        invalid = sorted(code for code in value if not _COUNTRY_CODE.match(code))
        if invalid:
            message = (
                f"Invalid ISO 3166-1 alpha-2 country codes: {invalid}. "
                "Use uppercase two-letter codes, e.g. 'GB' not 'United Kingdom' or 'gb'."
            )
            raise ValueError(message)
        return value

    def is_priority_country(self, country_code: str) -> bool:
        """Return whether ``country_code`` is an explicitly targeted country."""
        return country_code.upper() in self.priority_countries
