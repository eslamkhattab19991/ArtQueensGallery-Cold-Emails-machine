"""The ``ContactSource`` port: the one interface every contact method implements.

ARCHITECTURE.md §4.5.1 — the load-bearing extensibility point of the whole
system. A website scraper, a search query, a PDF parser, a WHOIS lookup, a
future browser agent: each is one file implementing this interface plus one line
in ``contact_sources.yaml``. The engine schedules them in cost tiers and runs a
tier's sources in parallel (§4.5.2); none of them knows another exists.

Two rules from the architecture are encoded here as types, not conventions:

* **Failures are values, not exceptions** (§4.5.1). ``search`` returns a
  :class:`ContactSourceResult` whose :class:`SourceOutcome` may be ``ERROR`` or
  ``TIMEOUT``. One source failing must never abort the parallel group, so it
  must not raise.
* **Ownership is not decided here** (§4.5.4). A source reports the addresses it
  found; whether an address is the artist's or a gallery's is classified later,
  in the merge layer, per candidate — because a gallery address surfaces from
  many sources and its ownership cannot be inferred from which one found it. A
  source therefore returns :class:`~prospecting.domain.models.contact.EmailCandidate`
  values whose ``ownership`` is provisional until the merge layer sets it.

Where the result types live. ARCHITECTURE.md's folder sketch placed
``ContactSourceResult`` under ``contact/``. It is defined here instead: the port
declares its own return contract, and a port may not import ``contact/`` (the
Import Linter forbids it), so the type the port returns cannot live there. The
``contact/`` engine imports these from the port, not the other way around.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from prospecting.domain.base import FrozenModel
from prospecting.domain.enums import ContactMethod, SourceTier
from prospecting.domain.identifiers import RunId
from prospecting.domain.models.artist import ArtistProfile
from prospecting.domain.models.contact import EmailCandidate, PhoneCandidate
from prospecting.schemas.envelope import CostRecord

__all__ = [
    "ContactSearchContext",
    "ContactSource",
    "ContactSourceResult",
    "CostEstimate",
    "SourceOutcome",
]


class SourceOutcome(StrEnum):
    """How a single source's run ended.

    Distinguished rather than collapsed to success/failure because the engine's
    stopping condition and the per-source metrics (ARCHITECTURE.md §4.5.2, §7)
    treat them differently: ``NO_RESULTS`` is a source that ran cleanly and found
    nothing, ``SKIPPED`` never ran because it did not apply, and the three
    failure modes are worth telling apart when tuning deadlines and budgets.
    """

    SUCCESS = "success"
    NO_RESULTS = "no_results"
    SKIPPED = "skipped"
    ERROR = "error"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"


class CostEstimate(FrozenModel):
    """A source's declared, a-priori cost per invocation.

    Coarse counts, not token-level actuals: the scheduler uses these to reason
    about tiers and per-artist budget *before* running anything. The actual
    spend a run incurred is reported afterwards as a
    :class:`~prospecting.schemas.envelope.CostRecord`, which is finer-grained
    (it carries real token counts). Estimate to plan; record to account.
    """

    crawls: int = Field(default=0, ge=0, description="Page fetches this source performs.")
    searches: int = Field(default=0, ge=0, description="Search-provider queries it performs.")
    llm_calls: int = Field(default=0, ge=0, description="Model completions it performs.")
    dns_lookups: int = Field(default=0, ge=0, description="DNS resolutions it performs.")


class ContactSearchContext(FrozenModel):
    """Run-scoped context handed to a source for one invocation.

    Deliberately carries no capabilities. A source depends only on the ports it
    needs, and those are injected into it when it is constructed (Interface
    Segregation, ARCHITECTURE.md §8): the ``cached_page`` source is built with a
    ``Cache`` and nothing else. Passing a fat context of every port here would
    undo exactly that separation. What belongs here is the per-invocation
    envelope the engine controls — which run this is, and how long the source
    may take before the engine cancels it.
    """

    run_id: RunId = Field(description="The run this search belongs to, for provenance and metrics.")
    deadline_seconds: float = Field(
        gt=0.0, description="Wall-clock budget for this invocation before the engine cancels it."
    )


class ContactSourceResult(FrozenModel):
    """Everything one source produced in one run, including how it went.

    The candidate collections are split by kind — emails and phones — because
    they are governed by different rules: an email can complete a lead (once its
    ownership is confirmed), a phone is enrichment only (ARCHITECTURE.md §0).
    Keeping them in separate typed fields means no downstream code has to
    re-discover which is which.
    """

    source_name: str = Field(min_length=1, description="Which source produced this result.")
    outcome: SourceOutcome = Field(description="How the run ended.")
    emails: tuple[EmailCandidate, ...] = Field(
        default=(),
        description="Email addresses found. Ownership is provisional until the merge layer.",
    )
    phones: tuple[PhoneCandidate, ...] = Field(
        default=(), description="Phone numbers found. Enrichment only — never completes a lead."
    )
    cost: CostRecord = Field(
        default_factory=CostRecord, description="Actual resources this invocation consumed."
    )
    latency_seconds: float = Field(ge=0.0, description="Wall-clock time this invocation took.")
    error: str | None = Field(
        default=None, description="Human-readable detail. Required when outcome is ERROR."
    )

    @property
    def found_anything(self) -> bool:
        """Whether this result carries at least one candidate of any kind."""
        return bool(self.emails or self.phones)

    @model_validator(mode="after")
    def _outcome_must_match_the_candidates(self) -> Self:
        """Keep the outcome and the payload from contradicting each other.

        A result that reports ``SUCCESS`` but carries nothing, or reports a
        non-success while carrying candidates, is internally inconsistent — and
        the engine's stopping condition reads the outcome, so the inconsistency
        would change scheduling based on a lie. The two are pinned together here.
        """
        if self.outcome is SourceOutcome.SUCCESS and not self.found_anything:
            message = "outcome is SUCCESS but no candidates were returned."
            raise ValueError(message)
        if self.outcome is not SourceOutcome.SUCCESS and self.found_anything:
            message = (
                f"outcome is {self.outcome.value!r} but candidates were returned; "
                "a result with candidates is a SUCCESS."
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _errors_must_explain_themselves(self) -> Self:
        """An ERROR outcome must say what went wrong, so metrics can group it."""
        if self.outcome is SourceOutcome.ERROR and not self.error:
            message = "outcome is ERROR but no error detail was given."
            raise ValueError(message)
        return self


@runtime_checkable
class ContactSource(Protocol):
    """One pluggable contact-discovery method.

    The attributes are declarative metadata the engine reads *without* running
    the source: its cost tier, its estimated cost, the inputs it needs, and the
    contact methods it can yield. Together they let the scheduler decide whether
    and when to run it. ``supports`` is a cheap, pure predicate — no I/O — while
    ``search`` is the actual, awaitable work.
    """

    name: str
    """Stable id, e.g. ``"artist_website"`` — recorded on every candidate's provenance."""

    tier: SourceTier
    """Which cost tier the engine schedules this source in (ARCHITECTURE.md §4.5.2)."""

    cost_estimate: CostEstimate
    """The a-priori cost the scheduler budgets for before invoking ``search``."""

    requires: frozenset[str]
    """Artist fields this source needs to run, e.g. ``frozenset({"website"})``."""

    provides: frozenset[ContactMethod]
    """The contact methods this source can yield — e.g. email, phone, or both."""

    def supports(self, artist: ArtistProfile) -> bool:
        """Whether this source can run for ``artist``, given what is known so far.

        A pure predicate: it inspects the artist (does she have a website, a
        domain, a social handle?) and returns a decision without any I/O. The
        engine calls it to skip sources whose ``requires`` are unmet before
        spending anything.
        """
        ...

    async def search(
        self, artist: ArtistProfile, context: ContactSearchContext
    ) -> ContactSourceResult:
        """Look for contact details for ``artist`` and return them as a result.

        Must not raise for an expected failure — a page that will not load, a
        query that errors, a deadline reached — which is reported through the
        result's :class:`SourceOutcome`. Raising would abort the whole parallel
        tier, which is the one thing the pluggable design must never allow.
        """
        ...
