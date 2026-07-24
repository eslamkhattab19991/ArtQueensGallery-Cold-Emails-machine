"""Tests for the ``DnsResolver`` port.

ARCHITECTURE.md §8: this is the Interface Segregation example — Stage 6 depends
on ``DnsResolver`` alone. The port reports facts; it does not decide
deliverability (ARCHITECTURE.md §7), which is why there is no confidence field
here — that judgement belongs to ``scoring/email_confidence``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from prospecting.ports.dns_resolver import DnsResolution, DnsResolver

_FIXED_INSTANT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def make_resolution(**overrides: object) -> DnsResolution:
    values: dict[str, object] = {
        "domain": "example-artist.com",
        "resolves": True,
        "has_mx": True,
        "mx_hosts": ("mx1.example-artist.com",),
        "checked_at": _FIXED_INSTANT,
    }
    values.update(overrides)
    return DnsResolution(**values)


class TestValidation:
    def test_requires_a_timezone_aware_timestamp(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_resolution(checked_at=datetime(2026, 7, 23, 12, 0))  # noqa: DTZ001

    def test_rejects_mx_hosts_without_has_mx(self) -> None:
        """An internally contradictory result must fail loudly, not pass through."""
        with pytest.raises(ValidationError, match="has_mx is False"):
            make_resolution(has_mx=False, mx_hosts=("mx1.example-artist.com",))

    def test_a_domain_with_no_mx_record_is_a_valid_result(self) -> None:
        """Absence of mail service is a fact this port reports, not an error."""
        resolution = make_resolution(has_mx=False, mx_hosts=())
        assert not resolution.has_mx

    def test_a_domain_that_does_not_resolve_is_a_valid_result(self) -> None:
        resolution = make_resolution(resolves=False, has_mx=False, mx_hosts=())
        assert not resolution.resolves

    def test_is_immutable(self) -> None:
        resolution = make_resolution()
        with pytest.raises(ValidationError, match="frozen"):
            resolution.has_mx = False  # type: ignore[misc]


class _FakeDnsResolver:
    async def resolve(self, domain: str) -> DnsResolution:
        return make_resolution(domain=domain)


class TestStructuralTyping:
    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeDnsResolver(), DnsResolver)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), DnsResolver)

    def test_the_fake_resolves_the_requested_domain(self) -> None:
        resolution = asyncio.run(_FakeDnsResolver().resolve("example-artist.com"))
        assert resolution.domain == "example-artist.com"
