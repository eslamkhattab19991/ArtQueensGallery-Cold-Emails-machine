"""The ``Crawler`` port: turn a URL into text, without interpreting it.

ARCHITECTURE.md §7: a crawl adapter's single responsibility is "URL -> text,
cached and rate-limited"; it explicitly does **not** parse meaning. Two adapters
implement this port (Firecrawl and an httpx fallback, per §3), and the pipeline
never knows which one it holds.

Expected failures — a 404, an anti-bot block, a timeout — are returned as a
:class:`CrawlResult` with a non-OK :class:`CrawlStatus`, not raised. A contact
source runs several crawls and must be able to treat "this page did not load"
as an ordinary outcome rather than an exception that aborts the others
(ARCHITECTURE.md §4.5.1, "failures are values"). Truly exceptional conditions
— a bug, a missing binary — may still raise.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from prospecting.domain.base import FrozenModel

__all__ = ["CrawlResult", "CrawlStatus", "Crawler"]


class CrawlStatus(StrEnum):
    """The outcome of a single fetch, as a value the caller can branch on.

    The non-OK members are deliberately distinct rather than a single ``ERROR``:
    a ``BLOCKED`` page might be retried through a different adapter, a
    ``NOT_FOUND`` never should, and a ``TIMEOUT`` is worth distinguishing from a
    hard failure when tuning per-source deadlines.
    """

    OK = "ok"
    NOT_FOUND = "not_found"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    ERROR = "error"


class CrawlResult(FrozenModel):
    """The text of one fetched page, plus enough context to trace and cache it.

    ``content`` is the extracted text (markdown for the Firecrawl adapter, raw
    text for the fallback); the port stays deliberately agnostic about which,
    because the parser that interprets it is a separate stage. ``fetched_at``
    feeds the :class:`~prospecting.domain.provenance.Provenance` of every value
    later read from this page, which is why it is required and timezone-aware.
    """

    url: str = Field(min_length=1, description="The URL that was requested.")
    status: CrawlStatus = Field(
        description="Whether the fetch succeeded, and how it failed if not."
    )
    content: str | None = Field(
        default=None, description="The page's extracted text. Present when status is OK."
    )
    final_url: str | None = Field(
        default=None, description="The URL after redirects, when it differs from the request."
    )
    status_code: int | None = Field(default=None, description="HTTP status code, when known.")
    error: str | None = Field(
        default=None, description="Human-readable detail for a non-OK status."
    )
    fetched_at: datetime = Field(description="When the fetch completed. Timezone-aware.")
    from_cache: bool = Field(
        default=False, description="Whether this result was served from the crawl cache."
    )

    @property
    def ok(self) -> bool:
        """Whether the fetch produced usable content.

        Both conditions matter: a status of OK with no content is not something
        a source can extract from, so the two are checked together here rather
        than left to each call site to remember.
        """
        return self.status is CrawlStatus.OK and self.content is not None

    @model_validator(mode="after")
    def _timestamp_must_be_timezone_aware(self) -> Self:
        """Reject naive timestamps, matching the provenance rule they feed."""
        if self.fetched_at.tzinfo is None:
            message = (
                f"fetched_at must be timezone-aware, got {self.fetched_at!r}. "
                "Use datetime.now(UTC)."
            )
            raise ValueError(message)
        return self


@runtime_checkable
class Crawler(Protocol):
    """Fetch the text of one URL.

    Single-URL by design: concurrency is the caller's concern. The contact
    engine fans out across sources with ``asyncio.gather`` (ARCHITECTURE.md
    §4.5.2), so a batch method here would duplicate scheduling that already
    lives one layer up and belongs there.
    """

    async def fetch(self, url: str) -> CrawlResult:
        """Fetch ``url`` and return its content or a non-OK result.

        Implementations must not raise for expected fetch failures — a missing
        page, an anti-bot block, a timeout — which are reported through
        :attr:`CrawlResult.status`.
        """
        ...
