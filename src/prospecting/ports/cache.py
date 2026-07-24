"""The ``Cache`` port: a keyed store for content a run would rather not refetch.

ARCHITECTURE.md §3 and §8: a contact source that reads already-fetched content
depends on ``Cache`` alone — not on ``Crawler``, ``SearchProvider``, or
``LLMClient``. This is the narrowest port in the system, and its narrowness is
the Interface Segregation point: the ``cached_page`` source (tier 0, always run,
free) needs nothing more than "give me what we already have for this key".

Async, though the first adapter is local disk. The interface is written for the
capability, not the current backend: a run distributed across machines will want
a shared cache (Redis, S3), and its ``get``/``put`` are naturally awaitable. A
synchronous disk adapter satisfies an async method trivially; the reverse would
force a breaking change the day a network cache is introduced.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Cache"]


@runtime_checkable
class Cache(Protocol):
    """A minimal async key/value store for text payloads."""

    async def get(self, key: str) -> str | None:
        """Return the value stored under ``key``, or ``None`` if absent or expired."""
        ...

    async def put(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        """Store ``value`` under ``key``.

        ``ttl_seconds`` is an optional expiry hint; ``None`` means the entry does
        not expire on its own. An adapter whose backend has no notion of expiry
        may ignore the hint, so callers must not rely on it for correctness —
        only as an optimisation.
        """
        ...
