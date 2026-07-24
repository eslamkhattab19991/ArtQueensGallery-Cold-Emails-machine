"""Tests for the contact-sources configuration model.

Validates the shape of ``contact_sources.yaml`` in isolation from the registry
that consumes it. The registry's reconciliation of config against registered
implementations is tested separately, in ``tests/unit/contact/test_registry``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from prospecting.config.models.contact_sources import (
    ContactSourceDefaults,
    ContactSourcesConfig,
    ContactSourceSettings,
)
from prospecting.domain.enums import SourceTier


def make_config(**overrides: object) -> ContactSourcesConfig:
    values: dict[str, object] = {
        "defaults": ContactSourceDefaults(timeout_seconds=30.0),
        "sources": {
            "artist_website": ContactSourceSettings(enabled=True, tier=SourceTier.CHEAP),
            "whois": ContactSourceSettings(enabled=False),
        },
    }
    values.update(overrides)
    return ContactSourcesConfig(**values)


class TestPerSourceOverrides:
    def test_only_enabled_is_required(self) -> None:
        """A source that needs no tuning is a single line: everything else defaults."""
        settings = ContactSourceSettings(enabled=True)
        assert settings.tier is None
        assert settings.timeout_seconds is None
        assert settings.priority == 0

    def test_tier_override_is_accepted(self) -> None:
        settings = ContactSourceSettings(enabled=True, tier=SourceTier.MODERATE)
        assert settings.tier is SourceTier.MODERATE

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ContactSourceSettings(enabled=True, timeout_seconds=0)

    def test_a_typo_in_a_per_source_key_is_rejected(self) -> None:
        """extra=forbid: 'enabld' must fail loudly, not be silently ignored."""
        with pytest.raises(ValidationError):
            ContactSourceSettings(enabld=True)  # type: ignore[call-arg]


class TestEnabledNames:
    def test_returns_only_the_enabled_sources(self) -> None:
        assert make_config().enabled_names() == frozenset({"artist_website"})

    def test_is_empty_when_nothing_is_enabled(self) -> None:
        config = make_config(
            sources={"whois": ContactSourceSettings(enabled=False)},
        )
        assert config.enabled_names() == frozenset()


class TestValidation:
    def test_rejects_a_blank_source_name(self) -> None:
        with pytest.raises(ValidationError, match="must not be blank"):
            make_config(sources={"   ": ContactSourceSettings(enabled=True)})

    def test_an_unknown_top_level_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContactSourcesConfig(
                defaults=ContactSourceDefaults(timeout_seconds=30.0),
                sources={},
                stopping_condition=0.8,  # type: ignore[call-arg]
            )

    def test_is_immutable(self) -> None:
        config = make_config()
        with pytest.raises(ValidationError, match="frozen"):
            config.sources = {}  # type: ignore[misc]

    def test_an_empty_source_table_is_valid(self) -> None:
        """A run with no contact sources configured is inert, but not malformed."""
        config = make_config(sources={})
        assert config.enabled_names() == frozenset()
