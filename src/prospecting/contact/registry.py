"""The contact-source registry: turn configuration into a runnable source set.

ARCHITECTURE.md §7 — ``contact/registry``: "Discover and enable sources from
config", and explicitly *not* execute them (that is the engine's job, built
later). The registry is the plugin system's core: it holds the sources that have
been registered (by the composition root), reads
:class:`~prospecting.config.models.contact_sources.ContactSourcesConfig`, and
produces the enabled sources with their effective tier and deadline, ordered
deterministically for the engine to run.

Registration is explicit, not magic. Sources are handed to the registry, not
discovered by scanning modules or entry points — the project favours
determinism and testability over auto-discovery, so "which sources exist" is a
readable argument at the composition root rather than a side effect of what
happened to be imported.

The registry is where the "one file plus one config line" contract is enforced:
enabling a source that has no implementation, or shipping an implementation with
no configuration entry, is caught here at startup with a message that names the
offending source — not discovered as a silent no-op mid-run.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from prospecting.config.models.contact_sources import ContactSourcesConfig
from prospecting.domain.enums import SourceTier
from prospecting.ports.contact_source import ContactSource

__all__ = ["ActivatedSource", "ContactSourceConfigurationError", "ContactSourceRegistry"]

#: Cost-tier execution order, derived from the enum's declaration order rather
#: than hard-coded: ``SourceTier`` is declared CACHED -> CHEAP -> MODERATE ->
#: EXPENSIVE precisely because that is the ascending cost sequence the scheduler
#: runs (ARCHITECTURE.md §4.5.2). Deriving it here keeps the two from drifting.
_TIER_ORDER: dict[SourceTier, int] = {tier: index for index, tier in enumerate(SourceTier)}


class ContactSourceConfigurationError(Exception):
    """Configuration and registered sources disagree in a way that must stop startup.

    Raised when a source is enabled with no implementation, when an
    implementation has no configuration entry, or when two registered sources
    share a name. Every case is a wiring mistake that would otherwise surface as
    a source that silently never runs — the exact failure the registry exists to
    make loud.
    """


@dataclass(frozen=True, slots=True)
class ActivatedSource:
    """A source configuration has switched on, paired with its effective settings.

    The engine consumes these rather than raw ``ContactSource`` objects, because
    ``tier`` and ``timeout_seconds`` here are the *resolved* values — the config
    override if one was given, otherwise the source's own default — so the engine
    never has to re-derive them.
    """

    source: ContactSource
    tier: SourceTier
    timeout_seconds: float
    priority: int

    @property
    def name(self) -> str:
        """The underlying source's stable name."""
        return self.source.name


class ContactSourceRegistry:
    """Resolve configured, enabled contact sources into a runnable, ordered set."""

    def __init__(self, *, sources: Iterable[ContactSource], config: ContactSourcesConfig) -> None:
        """Register ``sources`` and reconcile them against ``config``.

        Args:
            sources: The contact-source implementations available in this run,
                constructed by the composition root with the ports each needs.
            config: The parsed ``contact_sources.yaml`` section.

        Raises:
            ContactSourceConfigurationError: Two sources share a name, a
                registered source has no configuration entry, or configuration
                enables a source with no registered implementation.
        """
        registered: dict[str, ContactSource] = {}
        for source in sources:
            if source.name in registered:
                message = (
                    f"two contact sources are both named {source.name!r}; "
                    "source names must be unique."
                )
                raise ContactSourceConfigurationError(message)
            registered[source.name] = source

        self._registered = registered
        self._config = config
        self._reconcile()

    def _reconcile(self) -> None:
        """Fail unless every registered source and every enabled entry line up."""
        problems: list[str] = []

        unconfigured = sorted(name for name in self._registered if name not in self._config.sources)
        if unconfigured:
            problems.append(
                "registered contact sources have no entry in contact_sources.yaml "
                f"(add one, enabled true or false): {unconfigured}"
            )

        enabled_without_impl = sorted(
            name for name in self._config.enabled_names() if name not in self._registered
        )
        if enabled_without_impl:
            problems.append(
                "contact_sources.yaml enables sources with no registered implementation "
                f"(build them, or set enabled: false): {enabled_without_impl}"
            )

        if problems:
            raise ContactSourceConfigurationError("\n".join(problems))

    def activated(self) -> tuple[ActivatedSource, ...]:
        """Return the enabled sources with effective settings, in execution order.

        Ordered by tier (CACHED first), then by descending priority, then by name
        — a total order, so a run's source sequence is reproducible rather than
        dependent on dict iteration or registration order.
        """
        activated: list[ActivatedSource] = []
        for name, source in self._registered.items():
            settings = self._config.sources[name]  # present: guaranteed by _reconcile
            if not settings.enabled:
                continue
            activated.append(
                ActivatedSource(
                    source=source,
                    tier=settings.tier if settings.tier is not None else source.tier,
                    timeout_seconds=(
                        settings.timeout_seconds
                        if settings.timeout_seconds is not None
                        else self._config.defaults.timeout_seconds
                    ),
                    priority=settings.priority,
                )
            )
        return tuple(
            sorted(activated, key=lambda item: (_TIER_ORDER[item.tier], -item.priority, item.name))
        )

    def by_tier(self) -> dict[SourceTier, tuple[ActivatedSource, ...]]:
        """Group the activated sources by tier, tiers in execution order.

        The shape the engine schedules from: it runs one tier's sources in
        parallel, then evaluates the stopping condition before moving to the
        next. Only tiers that actually have an enabled source appear.
        """
        grouped: dict[SourceTier, list[ActivatedSource]] = {}
        for item in self.activated():
            grouped.setdefault(item.tier, []).append(item)
        return {tier: tuple(items) for tier, items in grouped.items()}

    def activated_names(self) -> tuple[str, ...]:
        """Return just the names of the activated sources, in execution order."""
        return tuple(item.name for item in self.activated())
