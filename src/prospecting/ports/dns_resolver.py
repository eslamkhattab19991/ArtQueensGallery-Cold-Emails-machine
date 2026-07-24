"""The ``DnsResolver`` port: report a domain's mail and address records.

ARCHITECTURE.md §7: the DNS adapter turns a "domain -> MX/A records, cached" and
explicitly does **not** decide deliverability. Reporting that a domain has no MX
record is a fact; concluding that an address is therefore undeliverable is a
scoring decision, and it lives in ``scoring/email_confidence`` (§4.6). Keeping
those apart is what lets the confidence rubric be retuned without touching the
resolver, and lets the resolver be swapped or mocked without touching scoring.

This is the one port Stage 6 (verification) depends on, and it depends on
nothing else — the Interface Segregation example called out in ARCHITECTURE.md
§8.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from prospecting.domain.base import FrozenModel

__all__ = ["DnsResolution", "DnsResolver"]


class DnsResolution(FrozenModel):
    """The record facts about one domain, without a deliverability verdict.

    ``has_mx`` is stored explicitly rather than derived from ``mx_hosts`` being
    non-empty, because "we looked and there is no MX" and "we have not recorded
    the hosts" are different claims, and only the first supports a confident
    downgrade of an address's score. ``checked_at`` feeds the
    :class:`~prospecting.domain.provenance.Provenance` of the verification
    result, so it is required and timezone-aware.
    """

    domain: str = Field(min_length=1, description="The domain that was resolved.")
    resolves: bool = Field(description="Whether the domain has an A/AAAA record — i.e. exists.")
    has_mx: bool = Field(description="Whether the domain publishes at least one MX record.")
    mx_hosts: tuple[str, ...] = Field(
        default=(), description="The MX target hosts, in the order returned."
    )
    checked_at: datetime = Field(description="When the lookup ran. Timezone-aware.")

    @model_validator(mode="after")
    def _mx_facts_must_agree(self) -> Self:
        """A domain cannot both have no MX and list MX hosts.

        Guards against an adapter populating ``mx_hosts`` while leaving
        ``has_mx`` false (or the reverse) — an internal contradiction that would
        make the record mean different things to different readers.
        """
        if self.mx_hosts and not self.has_mx:
            message = f"has_mx is False but mx_hosts is non-empty: {self.mx_hosts!r}."
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _timestamp_must_be_timezone_aware(self) -> Self:
        """Reject naive timestamps, matching the provenance rule they feed."""
        if self.checked_at.tzinfo is None:
            message = (
                f"checked_at must be timezone-aware, got {self.checked_at!r}. "
                "Use datetime.now(UTC)."
            )
            raise ValueError(message)
        return self


@runtime_checkable
class DnsResolver(Protocol):
    """Look up the mail and address records for one domain."""

    async def resolve(self, domain: str) -> DnsResolution:
        """Resolve ``domain`` and report its A/MX facts.

        A domain that does not exist is reported as a :class:`DnsResolution`
        with ``resolves=False`` and ``has_mx=False`` — an ordinary outcome, not
        an exception.
        """
        ...
