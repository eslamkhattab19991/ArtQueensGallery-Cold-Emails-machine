"""Tests for the ``SearchProvider`` port."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from prospecting.ports.search_provider import SearchHit, SearchProvider


def make_hit(**overrides: object) -> SearchHit:
    values: dict[str, object] = {
        "url": "https://example-artist.com/about",
        "rank": 1,
        "engine": "serper",
    }
    values.update(overrides)
    return SearchHit(**values)


class TestValidation:
    def test_rank_must_be_at_least_one(self) -> None:
        """A search result has no position zero — ranks are 1-based."""
        with pytest.raises(ValidationError):
            make_hit(rank=0)

    def test_rejects_an_empty_engine_id(self) -> None:
        with pytest.raises(ValidationError):
            make_hit(engine="")

    def test_title_and_snippet_are_optional(self) -> None:
        hit = make_hit()
        assert hit.title is None
        assert hit.snippet is None

    def test_is_immutable(self) -> None:
        hit = make_hit()
        with pytest.raises(ValidationError, match="frozen"):
            hit.rank = 2  # type: ignore[misc]


class TestEngineRecordsProvenance:
    """The engine field is what lets corroboration tell two providers apart."""

    def test_two_hits_for_the_same_url_from_different_engines_are_distinguishable(
        self,
    ) -> None:
        from_serper = make_hit(engine="serper")
        from_brave = make_hit(engine="brave")
        assert from_serper.url == from_brave.url
        assert from_serper.engine != from_brave.engine


class _FakeSearchProvider:
    name = "fake_engine"

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        del query
        return [make_hit(rank=i + 1) for i in range(min(limit, 3))]


class TestStructuralTyping:
    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeSearchProvider(), SearchProvider)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), SearchProvider)

    def test_the_fake_returns_ranked_hits_up_to_the_limit(self) -> None:
        hits = asyncio.run(_FakeSearchProvider().search("Jane Doe artist", limit=2))
        assert [hit.rank for hit in hits] == [1, 2]

    def test_a_query_with_no_results_is_an_empty_list_not_an_error(self) -> None:
        hits = asyncio.run(_FakeSearchProvider().search("Jane Doe artist", limit=0))
        assert hits == []
