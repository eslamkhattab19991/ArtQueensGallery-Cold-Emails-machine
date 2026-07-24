"""Tests for the ``ContactSource`` port — ARCHITECTURE.md §4.5.1's extensibility point.

Two business rules are enforced here as types: failures are values, never
exceptions (so ``ContactSourceResult`` must not let an outcome contradict its
own payload), and ownership is never decided by the source itself — the
:class:`~prospecting.domain.models.contact.EmailCandidate` values a source
returns carry whatever ownership they were constructed with, and it is the
merge layer's job (not tested here) to set it authoritatively.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from prospecting.domain.enums import ContactMethod, EmailOwnership, SourceTier
from prospecting.domain.identifiers import CanonicalId, RunId
from prospecting.domain.models.artist import ArtistProfile
from prospecting.domain.provenance import Provenanced
from prospecting.ports.contact_source import (
    ContactSearchContext,
    ContactSource,
    ContactSourceResult,
    CostEstimate,
    SourceOutcome,
)
from tests.support.factories import make_email_candidate, make_phone_candidate, make_provenance

_RUN = RunId("run_2026-07-24_001")


def make_artist(**overrides: object) -> ArtistProfile:
    values: dict[str, object] = {
        "canonical_id": CanonicalId("art_8f3a2b1c"),
        "full_name": Provenanced[str](value="Jane Doe", provenance=make_provenance()),
    }
    values.update(overrides)
    return ArtistProfile(**values)


def make_context(**overrides: object) -> ContactSearchContext:
    values: dict[str, object] = {"run_id": _RUN, "deadline_seconds": 30.0}
    values.update(overrides)
    return ContactSearchContext(**values)


def make_result(**overrides: object) -> ContactSourceResult:
    values: dict[str, object] = {
        "source_name": "artist_website",
        "outcome": SourceOutcome.SUCCESS,
        "emails": (make_email_candidate(),),
        "latency_seconds": 0.4,
    }
    values.update(overrides)
    return ContactSourceResult(**values)


class TestCostEstimate:
    def test_defaults_to_zero_of_everything(self) -> None:
        estimate = CostEstimate()
        assert estimate.crawls == 0
        assert estimate.searches == 0
        assert estimate.llm_calls == 0
        assert estimate.dns_lookups == 0

    def test_rejects_a_negative_count(self) -> None:
        with pytest.raises(ValidationError):
            CostEstimate(crawls=-1)


class TestContactSearchContext:
    def test_deadline_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            make_context(deadline_seconds=0)

    def test_is_immutable(self) -> None:
        context = make_context()
        with pytest.raises(ValidationError, match="frozen"):
            context.deadline_seconds = 10.0  # type: ignore[misc]


class TestContactSourceResultConsistency:
    """The outcome and the payload must not be able to disagree.

    ARCHITECTURE.md §4.5.1: ``ContactSourceResult`` carries the outcome, so the
    engine's stopping condition can trust it without re-deriving the truth from
    the candidate lists on every read.
    """

    def test_success_requires_at_least_one_candidate(self) -> None:
        with pytest.raises(ValidationError, match="SUCCESS but no candidates"):
            make_result(outcome=SourceOutcome.SUCCESS, emails=(), phones=())

    def test_no_results_must_carry_no_candidates(self) -> None:
        with pytest.raises(ValidationError, match="candidates were returned"):
            make_result(outcome=SourceOutcome.NO_RESULTS, emails=(make_email_candidate(),))

    def test_no_results_with_nothing_found_is_valid(self) -> None:
        result = make_result(outcome=SourceOutcome.NO_RESULTS, emails=(), phones=())
        assert not result.found_anything

    def test_a_phone_only_result_still_counts_as_found(self) -> None:
        result = make_result(
            outcome=SourceOutcome.SUCCESS, emails=(), phones=(make_phone_candidate(),)
        )
        assert result.found_anything

    def test_error_requires_an_explanation(self) -> None:
        with pytest.raises(ValidationError, match="no error detail"):
            make_result(outcome=SourceOutcome.ERROR, emails=(), phones=(), error=None)

    def test_error_with_a_message_is_valid(self) -> None:
        result = make_result(
            outcome=SourceOutcome.ERROR, emails=(), phones=(), error="connection reset"
        )
        assert result.outcome is SourceOutcome.ERROR

    @pytest.mark.parametrize(
        "outcome", [SourceOutcome.SKIPPED, SourceOutcome.TIMEOUT, SourceOutcome.BUDGET_EXCEEDED]
    )
    def test_the_remaining_non_success_outcomes_carry_no_candidates(
        self, outcome: SourceOutcome
    ) -> None:
        result = make_result(outcome=outcome, emails=(), phones=())
        assert not result.found_anything


class TestOwnershipIsNotDecidedBySources:
    """A source's candidates carry whatever ownership they were built with.

    The port does not gate or reclassify — that is the merge layer's job
    (ARCHITECTURE.md §4.5.4). This test documents the boundary: nothing in
    ``ContactSourceResult`` prevents a source from returning a GALLERY-owned
    candidate, because the source is not the authority on ownership.
    """

    def test_a_result_may_carry_a_provisional_gallery_owned_candidate(self) -> None:
        result = make_result(
            emails=(make_email_candidate(ownership=EmailOwnership.GALLERY),),
        )
        assert result.emails[0].ownership is EmailOwnership.GALLERY


class _FakeContactSource:
    """The minimal shape of a ``ContactSource`` — no base class, by design."""

    name = "fake_source"
    tier = SourceTier.CHEAP
    cost_estimate = CostEstimate(crawls=1)
    requires = frozenset({"website"})
    provides = frozenset({ContactMethod.EMAIL})

    def supports(self, artist: ArtistProfile) -> bool:
        return artist.website is not None

    async def search(
        self, artist: ArtistProfile, context: ContactSearchContext
    ) -> ContactSourceResult:
        del artist, context
        return make_result(source_name=self.name)


class TestStructuralTyping:
    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeContactSource(), ContactSource)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), ContactSource)

    def test_supports_is_a_pure_predicate_with_no_io(self) -> None:
        source = _FakeContactSource()
        assert not source.supports(make_artist())
        assert source.supports(
            make_artist(
                website=Provenanced[str](value="https://jane-doe.art", provenance=make_provenance())
            )
        )

    def test_search_returns_a_result_naming_the_source(self) -> None:
        source = _FakeContactSource()
        result = asyncio.run(source.search(make_artist(), make_context()))
        assert result.source_name == "fake_source"

    def test_provides_declares_what_it_can_yield(self) -> None:
        assert ContactMethod.EMAIL in _FakeContactSource.provides
        assert ContactMethod.PHONE not in _FakeContactSource.provides
