"""Tests for the ``Crawler`` port's data contract and structural typing.

No adapter exists yet (Phase 6). What is tested here is the port itself: the
invariants on :class:`CrawlResult` and the fact that a minimal object shaped
like a ``Crawler`` satisfies the protocol without inheriting from anything —
the property the whole adapter layer depends on.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from prospecting.ports.crawler import Crawler, CrawlResult, CrawlStatus

_FIXED_INSTANT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def make_result(**overrides: object) -> CrawlResult:
    values: dict[str, object] = {
        "url": "https://example-artist.com",
        "status": CrawlStatus.OK,
        "content": "# Jane Doe\nPainter.",
        "fetched_at": _FIXED_INSTANT,
    }
    values.update(overrides)
    return CrawlResult(**values)


class TestOk:
    def test_true_when_status_ok_and_content_present(self) -> None:
        assert make_result().ok

    def test_false_when_status_ok_but_content_missing(self) -> None:
        """A crawler that reports success with nothing to show is not usable."""
        assert not make_result(content=None).ok

    @pytest.mark.parametrize(
        "status",
        [CrawlStatus.NOT_FOUND, CrawlStatus.BLOCKED, CrawlStatus.TIMEOUT, CrawlStatus.ERROR],
    )
    def test_false_for_every_non_ok_status(self, status: CrawlStatus) -> None:
        assert not make_result(status=status, content=None).ok


class TestValidation:
    def test_requires_a_timezone_aware_timestamp(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_result(fetched_at=datetime(2026, 7, 23, 12, 0))  # noqa: DTZ001

    def test_rejects_an_empty_url(self) -> None:
        with pytest.raises(ValidationError):
            make_result(url="")

    def test_is_immutable(self) -> None:
        result = make_result()
        with pytest.raises(ValidationError, match="frozen"):
            result.status = CrawlStatus.ERROR  # type: ignore[misc]


class _FakeCrawler:
    """The minimal shape of a ``Crawler`` — no base class, by design."""

    async def fetch(self, url: str) -> CrawlResult:
        return make_result(url=url)


class TestStructuralTyping:
    """A ``Crawler`` is satisfied by shape alone (ARCHITECTURE.md §8, DIP)."""

    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeCrawler(), Crawler)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), Crawler)

    def test_the_fake_is_awaitable_and_returns_a_result(self) -> None:
        result = asyncio.run(_FakeCrawler().fetch("https://example-artist.com"))
        assert result.ok
