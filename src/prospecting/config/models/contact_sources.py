"""Configuration for the pluggable contact-discovery sources (``contact_sources.yaml``).

ARCHITECTURE.md §4.5: contact discovery is an open set of sources, each behind
the ``ContactSource`` port, switched on and ordered *purely by configuration* —
"``tier:`` is a ``contact_sources.yaml`` field, not a code constant" (§4.5.2).
This module is the typed, validated shape of that file. The registry
(:mod:`prospecting.contact.registry`) consumes it to decide which registered
sources run, in which tier, with what deadline.

A source declared here is inert until its implementation is registered with the
registry by the composition root. Declaring it is how an operator expresses
intent ("I want WHOIS lookups on"); the implementation landing is what makes
that intent take effect. The registry reconciles the two and fails loudly if
configuration enables a source that has no implementation.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from prospecting.config.models.base import FrozenConfig
from prospecting.domain.enums import SourceTier

__all__ = ["ContactSourceDefaults", "ContactSourceSettings", "ContactSourcesConfig"]


class ContactSourceSettings(FrozenConfig):
    """Configuration for one contact source.

    Every field except ``enabled`` is an override: left unset, the source keeps
    the default it declares in code (its ``tier``) or the shared default from
    :class:`ContactSourceDefaults` (its ``timeout_seconds``). This is what makes
    a source reorderable and re-budgetable without a code change, while a source
    that needs no tuning is a single ``enabled:`` line.
    """

    enabled: bool = Field(description="Whether this source runs at all.")
    tier: SourceTier | None = Field(
        default=None,
        description="Override the source's declared cost tier. None keeps the code default.",
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0.0,
        description="Override the per-invocation deadline. None uses the shared default.",
    )
    priority: int = Field(
        default=0,
        description="Ordering within a tier: higher runs first, ties broken by name.",
    )


class ContactSourceDefaults(FrozenConfig):
    """Fallback values applied to any source that does not set its own.

    Kept separate from the per-source table so the common case — every source
    shares one deadline — is stated once rather than repeated on each entry.
    """

    timeout_seconds: float = Field(
        gt=0.0, description="Default per-invocation deadline for a source that sets none."
    )


class ContactSourcesConfig(FrozenConfig):
    """The complete contact-source configuration for a run.

    ``sources`` is a mapping keyed by source name rather than a list, so a
    profile overlay can retune or disable one source without restating the whole
    table — the loader merges mappings key by key but replaces lists wholesale
    (see :func:`prospecting.config.sources.deep_merge`).
    """

    defaults: ContactSourceDefaults = Field(
        description="Fallback values for unset per-source fields."
    )
    sources: dict[str, ContactSourceSettings] = Field(
        description="Per-source configuration, keyed by the source's stable name."
    )

    @model_validator(mode="after")
    def _source_names_must_not_be_blank(self) -> ContactSourcesConfig:
        """Reject an empty source name, which no ``ContactSource`` can ever match.

        A blank key is always a YAML mistake (an indentation slip, a stray
        colon). Caught here it names the file; left alone it becomes a source
        that can never be registered and is silently never run.
        """
        if any(not name.strip() for name in self.sources):
            message = (
                "contact source names must not be blank; check indentation in contact_sources.yaml."
            )
            raise ValueError(message)
        return self

    def enabled_names(self) -> frozenset[str]:
        """Return the names of every source configured as enabled."""
        return frozenset(name for name, settings in self.sources.items() if settings.enabled)
