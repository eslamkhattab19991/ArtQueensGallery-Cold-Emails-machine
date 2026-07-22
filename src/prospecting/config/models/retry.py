"""Retry and backoff policy for transient failures."""

from __future__ import annotations

from pydantic import Field, model_validator

from prospecting.config.models.base import FrozenConfig

__all__ = ["RetryConfig"]


class RetryConfig(FrozenConfig):
    """Exponential backoff policy applied to retryable outbound failures.

    Only transient failures are retried. A 404 will still be a 404 on the third
    attempt; retrying it wastes budget and delays the run. The retryable status
    codes are therefore configuration rather than a hard-coded list, because
    which codes are transient varies by provider.
    """

    max_attempts: int = Field(
        ge=1, description="Total attempts including the first. 1 disables retrying."
    )
    initial_delay_seconds: float = Field(gt=0.0, description="Delay before the second attempt.")
    max_delay_seconds: float = Field(
        gt=0.0, description="Ceiling on backoff, so long runs cannot stall indefinitely."
    )
    backoff_multiplier: float = Field(
        ge=1.0, description="Delay growth factor per attempt. 1.0 gives constant delay."
    )
    jitter: bool = Field(
        description="Randomise delays to avoid synchronised retries hammering a recovering host."
    )
    retryable_status_codes: frozenset[int] = Field(
        description="HTTP statuses treated as transient. Others fail immediately."
    )

    @model_validator(mode="after")
    def _ceiling_must_exceed_floor(self) -> RetryConfig:
        """Reject a maximum delay below the initial delay.

        Such a policy silently clamps the first backoff, making the configured
        initial delay a lie.
        """
        if self.max_delay_seconds < self.initial_delay_seconds:
            message = (
                f"max_delay_seconds ({self.max_delay_seconds}) is below "
                f"initial_delay_seconds ({self.initial_delay_seconds}); "
                "the initial delay would be silently clamped"
            )
            raise ValueError(message)
        return self

    def delay_for_attempt(self, attempt: int) -> float:
        """Return the backoff delay in seconds before ``attempt``.

        Args:
            attempt: 1-based attempt number. Attempt 1 is the initial try and
                has no preceding delay.

        Returns:
            Seconds to wait, clamped to ``max_delay_seconds``. Jitter is applied
            by the caller so that this function stays deterministic and testable.
        """
        if attempt <= 1:
            return 0.0
        raw = self.initial_delay_seconds * (self.backoff_multiplier ** (attempt - 2))
        return min(raw, self.max_delay_seconds)
