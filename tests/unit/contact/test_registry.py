"""Tests for the contact-source registry — the plugin system's core.

Two things are proven here: that configuration and registered implementations
are reconciled loudly (a source enabled with no code, or code with no config,
stops startup), and that the enabled set comes out in a deterministic execution
order the engine can trust.
"""

from __future__ import annotations

import pytest

from prospecting.config.loader import load_settings
from prospecting.config.models.contact_sources import (
    ContactSourceDefaults,
    ContactSourcesConfig,
    ContactSourceSettings,
)
from prospecting.contact.registry import (
    ActivatedSource,
    ContactSourceConfigurationError,
    ContactSourceRegistry,
)
from prospecting.domain.enums import ContactMethod, SourceTier
from prospecting.domain.models.artist import ArtistProfile
from prospecting.ports.contact_source import (
    ContactSearchContext,
    ContactSourceResult,
    CostEstimate,
    SourceOutcome,
)


class _FakeSource:
    """A minimal ``ContactSource`` used only for its name and declared tier."""

    def __init__(self, name: str, tier: SourceTier) -> None:
        self.name = name
        self.tier = tier
        self.cost_estimate = CostEstimate()
        self.requires: frozenset[str] = frozenset()
        self.provides: frozenset[ContactMethod] = frozenset({ContactMethod.EMAIL})

    def supports(self, artist: ArtistProfile) -> bool:
        del artist
        return True

    async def search(
        self, artist: ArtistProfile, context: ContactSearchContext
    ) -> ContactSourceResult:
        del artist, context
        return ContactSourceResult(
            source_name=self.name, outcome=SourceOutcome.NO_RESULTS, latency_seconds=0.0
        )


def make_config(
    sources: dict[str, ContactSourceSettings], *, timeout: float = 30.0
) -> ContactSourcesConfig:
    return ContactSourcesConfig(
        defaults=ContactSourceDefaults(timeout_seconds=timeout), sources=sources
    )


class TestReconciliation:
    """Every registered source and every enabled entry must line up at startup."""

    def test_rejects_two_sources_with_the_same_name(self) -> None:
        with pytest.raises(ContactSourceConfigurationError, match="unique"):
            ContactSourceRegistry(
                sources=[
                    _FakeSource("artist_website", SourceTier.CHEAP),
                    _FakeSource("artist_website", SourceTier.MODERATE),
                ],
                config=make_config({"artist_website": ContactSourceSettings(enabled=True)}),
            )

    def test_rejects_a_registered_source_with_no_config_entry(self) -> None:
        """Adding a source is 'one file plus one config line' — the line is required."""
        with pytest.raises(ContactSourceConfigurationError, match="no entry"):
            ContactSourceRegistry(
                sources=[_FakeSource("mailto_scan", SourceTier.CHEAP)],
                config=make_config({}),
            )

    def test_rejects_config_enabling_a_source_with_no_implementation(self) -> None:
        with pytest.raises(ContactSourceConfigurationError, match="no registered implementation"):
            ContactSourceRegistry(
                sources=[],
                config=make_config({"whois": ContactSourceSettings(enabled=True)}),
            )

    def test_allows_a_disabled_entry_with_no_implementation(self) -> None:
        """A source can be declared and switched off before its code exists."""
        registry = ContactSourceRegistry(
            sources=[],
            config=make_config({"whois": ContactSourceSettings(enabled=False)}),
        )
        assert registry.activated() == ()

    def test_reports_every_reconciliation_problem_at_once(self) -> None:
        """One startup should surface both a missing config and a missing impl."""
        with pytest.raises(ContactSourceConfigurationError) as exc_info:
            ContactSourceRegistry(
                sources=[_FakeSource("mailto_scan", SourceTier.CHEAP)],
                config=make_config({"whois": ContactSourceSettings(enabled=True)}),
            )
        message = str(exc_info.value)
        assert "mailto_scan" in message
        assert "whois" in message


class TestActivation:
    def test_only_enabled_sources_are_activated(self) -> None:
        registry = ContactSourceRegistry(
            sources=[
                _FakeSource("artist_website", SourceTier.CHEAP),
                _FakeSource("whois", SourceTier.EXPENSIVE),
            ],
            config=make_config(
                {
                    "artist_website": ContactSourceSettings(enabled=True),
                    "whois": ContactSourceSettings(enabled=False),
                }
            ),
        )
        assert registry.activated_names() == ("artist_website",)

    def test_tier_falls_back_to_the_sources_default(self) -> None:
        registry = ContactSourceRegistry(
            sources=[_FakeSource("artist_website", SourceTier.CHEAP)],
            config=make_config({"artist_website": ContactSourceSettings(enabled=True)}),
        )
        assert registry.activated()[0].tier is SourceTier.CHEAP

    def test_config_overrides_the_sources_tier(self) -> None:
        """ARCHITECTURE.md §4.5.2: tier is reorderable by config, not a code constant."""
        registry = ContactSourceRegistry(
            sources=[_FakeSource("artist_website", SourceTier.CHEAP)],
            config=make_config(
                {"artist_website": ContactSourceSettings(enabled=True, tier=SourceTier.MODERATE)}
            ),
        )
        assert registry.activated()[0].tier is SourceTier.MODERATE

    def test_timeout_falls_back_to_the_shared_default(self) -> None:
        registry = ContactSourceRegistry(
            sources=[_FakeSource("artist_website", SourceTier.CHEAP)],
            config=make_config(
                {"artist_website": ContactSourceSettings(enabled=True)}, timeout=45.0
            ),
        )
        assert registry.activated()[0].timeout_seconds == 45.0

    def test_per_source_timeout_overrides_the_default(self) -> None:
        registry = ContactSourceRegistry(
            sources=[_FakeSource("artist_website", SourceTier.CHEAP)],
            config=make_config(
                {"artist_website": ContactSourceSettings(enabled=True, timeout_seconds=5.0)},
                timeout=45.0,
            ),
        )
        assert registry.activated()[0].timeout_seconds == 5.0


class TestOrdering:
    """The activated sequence is a total order, so runs are reproducible."""

    def test_tiers_run_cheapest_first(self) -> None:
        registry = ContactSourceRegistry(
            sources=[
                _FakeSource("whois", SourceTier.EXPENSIVE),
                _FakeSource("cached_page", SourceTier.CACHED),
                _FakeSource("artist_website", SourceTier.CHEAP),
            ],
            config=make_config(
                {
                    "whois": ContactSourceSettings(enabled=True),
                    "cached_page": ContactSourceSettings(enabled=True),
                    "artist_website": ContactSourceSettings(enabled=True),
                }
            ),
        )
        assert registry.activated_names() == ("cached_page", "artist_website", "whois")

    def test_higher_priority_runs_first_within_a_tier(self) -> None:
        registry = ContactSourceRegistry(
            sources=[
                _FakeSource("mailto_scan", SourceTier.CHEAP),
                _FakeSource("artist_website", SourceTier.CHEAP),
            ],
            config=make_config(
                {
                    "mailto_scan": ContactSourceSettings(enabled=True, priority=1),
                    "artist_website": ContactSourceSettings(enabled=True, priority=10),
                }
            ),
        )
        assert registry.activated_names() == ("artist_website", "mailto_scan")

    def test_equal_priority_breaks_on_name(self) -> None:
        registry = ContactSourceRegistry(
            sources=[
                _FakeSource("mailto_scan", SourceTier.CHEAP),
                _FakeSource("artist_website", SourceTier.CHEAP),
            ],
            config=make_config(
                {
                    "mailto_scan": ContactSourceSettings(enabled=True),
                    "artist_website": ContactSourceSettings(enabled=True),
                }
            ),
        )
        assert registry.activated_names() == ("artist_website", "mailto_scan")


class TestByTier:
    def test_groups_activated_sources_by_tier_in_order(self) -> None:
        registry = ContactSourceRegistry(
            sources=[
                _FakeSource("cached_page", SourceTier.CACHED),
                _FakeSource("artist_website", SourceTier.CHEAP),
                _FakeSource("mailto_scan", SourceTier.CHEAP),
            ],
            config=make_config(
                {
                    "cached_page": ContactSourceSettings(enabled=True),
                    "artist_website": ContactSourceSettings(enabled=True),
                    "mailto_scan": ContactSourceSettings(enabled=True),
                }
            ),
        )
        grouped = registry.by_tier()
        assert list(grouped) == [SourceTier.CACHED, SourceTier.CHEAP]
        assert len(grouped[SourceTier.CHEAP]) == 2

    def test_omits_tiers_with_no_enabled_source(self) -> None:
        registry = ContactSourceRegistry(
            sources=[_FakeSource("cached_page", SourceTier.CACHED)],
            config=make_config({"cached_page": ContactSourceSettings(enabled=True)}),
        )
        assert list(registry.by_tier()) == [SourceTier.CACHED]


class TestActivatedSource:
    def test_name_reads_through_to_the_source(self) -> None:
        source = _FakeSource("artist_website", SourceTier.CHEAP)
        activated = ActivatedSource(
            source=source, tier=SourceTier.CHEAP, timeout_seconds=30.0, priority=0
        )
        assert activated.name == "artist_website"


class TestShippedConfigurationIsRegistryConsistent:
    """The committed contact_sources.yaml must be a coherent registry input.

    Registered fakes standing in for every declared source must reconcile
    cleanly and activate in ascending tier order — proving the shipped file is
    not just parseable but internally consistent, the same guarantee
    ``TestShippedConfiguration`` gives the rest of config.
    """

    def _shipped_config(self) -> ContactSourcesConfig:
        return load_settings(environ={}).contact_sources

    def test_every_declared_source_reconciles_and_activates(self) -> None:
        config = self._shipped_config()
        fakes = [
            _FakeSource(name, settings.tier if settings.tier is not None else SourceTier.CHEAP)
            for name, settings in config.sources.items()
        ]
        registry = ContactSourceRegistry(sources=fakes, config=config)
        assert set(registry.activated_names()) == set(config.sources)

    def test_the_declared_source_set_is_the_ten_from_the_architecture(self) -> None:
        assert set(self._shipped_config().sources) == {
            "cached_page",
            "artist_website",
            "mailto_scan",
            "site_scoped_search",
            "open_web_search",
            "pdf_document",
            "social_profile",
            "public_directory",
            "whois",
            "gallery_page",
        }

    def test_gallery_page_runs_in_the_last_tier(self) -> None:
        """§4.5.2: it yields only an indirect contact, so it must never run early."""
        config = self._shipped_config()
        assert config.sources["gallery_page"].tier is SourceTier.EXPENSIVE

    def test_activation_is_ordered_by_ascending_tier(self) -> None:
        config = self._shipped_config()
        fakes = [
            _FakeSource(name, settings.tier if settings.tier is not None else SourceTier.CHEAP)
            for name, settings in config.sources.items()
        ]
        registry = ContactSourceRegistry(sources=fakes, config=config)
        tiers = [activated.tier for activated in registry.activated()]
        assert tiers[0] is SourceTier.CACHED
        assert tiers[-1] is SourceTier.EXPENSIVE
