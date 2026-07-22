"""Concurrency, timeout, and rate-limit settings."""

from __future__ import annotations

from pydantic import Field

from prospecting.config.models.base import FrozenConfig

__all__ = ["RuntimeConfig"]


class RuntimeConfig(FrozenConfig):
    """How aggressively the pipeline may talk to the outside world.

    Two independent concurrency limits are needed rather than one. The global
    limit protects our own budget and process; the per-domain limit protects the
    sites being crawled. A single global limit of 20 could still direct all 20
    requests at one small artist's website.
    """

    max_concurrent_requests: int = Field(
        ge=1, description="Upper bound on in-flight outbound requests across all hosts."
    )
    max_concurrent_per_domain: int = Field(
        ge=1, description="Upper bound on in-flight requests to any single host."
    )
    request_timeout_seconds: float = Field(
        gt=0.0, description="Per-request timeout before a source is treated as unavailable."
    )
    default_requests_per_minute: float = Field(
        gt=0.0, description="Default politeness rate applied to any host without an override."
    )
    per_domain_requests_per_minute: dict[str, float] = Field(
        default_factory=dict,
        description="Host-specific rate overrides, e.g. platforms with published limits.",
    )
    respect_robots_txt: bool = Field(
        description="Whether crawlers honour robots.txt. Disabling requires legal sign-off."
    )
    user_agent: str = Field(
        min_length=1,
        description="Identifies our crawler and how to contact us; required for polite crawling.",
    )

    def requests_per_minute_for(self, domain: str) -> float:
        """Return the rate limit for ``domain``, falling back to the default."""
        return self.per_domain_requests_per_minute.get(domain, self.default_requests_per_minute)
