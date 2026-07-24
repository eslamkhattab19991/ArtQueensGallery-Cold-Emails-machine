"""Tests for the ``Cache`` port.

ARCHITECTURE.md §8: the narrowest port in the system — the ``cached_page``
contact source (tier 0, always run, free) depends on this and nothing else.
There is no dedicated DTO to validate here; what matters is that the shape is
this small and that a trivial in-memory object satisfies it.
"""

from __future__ import annotations

import asyncio

from prospecting.ports.cache import Cache


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def put(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        del ttl_seconds  # An in-memory fake has no expiry to honour.
        self._store[key] = value


class TestStructuralTyping:
    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeCache(), Cache)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), Cache)


class TestFakeBehaviour:
    """Exercises the contract every real adapter (disk, Redis, ...) must honour."""

    def test_a_missing_key_returns_none(self) -> None:
        assert asyncio.run(_FakeCache().get("absent")) is None

    def test_a_stored_value_is_returned(self) -> None:
        async def scenario() -> str | None:
            cache = _FakeCache()
            await cache.put("https://example-artist.com/contact", "<html>...</html>")
            return await cache.get("https://example-artist.com/contact")

        assert asyncio.run(scenario()) == "<html>...</html>"

    def test_ttl_is_accepted_but_not_required_to_do_anything(self) -> None:
        """A backend without expiry support may ignore the hint — that is legal."""

        async def scenario() -> str | None:
            cache = _FakeCache()
            await cache.put("key", "value", ttl_seconds=60)
            return await cache.get("key")

        assert asyncio.run(scenario()) == "value"
