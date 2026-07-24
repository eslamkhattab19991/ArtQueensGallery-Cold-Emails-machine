"""The run-level budget guard: stop a run before it drains a provider balance.

ARCHITECTURE.md §9 and the ``pipeline/orchestrator`` responsibility (§7): a run
enforces spending ceilings so a runaway query expansion or a crawl loop cannot
quietly burn the month's API budget. This guard accumulates what a run has spent
and reports when a ceiling is breached; the orchestrator and the stage loop read
that verdict to stop cleanly at a resumable point (BudgetConfig docstring: "stops
a run at a resumable checkpoint rather than aborting").

This is the *per-run* guard. It is distinct from ``contact/budget.py``, the
*per-artist* ceiling that caps how much one artist's contact discovery may spend
before the engine gives up on that artist. Two different questions — "has this
run spent too much?" and "have we spent enough on this one artist?" — so two
different guards.

Scope. It enforces the three unit ceilings that a :class:`CostRecord` reports
directly — crawls, searches, and LLM calls. The monetary ceiling
(``max_usd_per_run``) is deliberately *not* enforced here: converting units to
dollars needs a per-model price table that arrives with the LLM adapter, and
inventing prices now would enforce a fiction. Until then the unit ceilings are
the guard rails, and this boundary is stated rather than silent.
"""

from __future__ import annotations

from prospecting.config.models.budget import BudgetConfig
from prospecting.schemas.envelope import CostRecord

__all__ = ["BudgetGuard"]


class BudgetGuard:
    """Accumulates a run's spend and reports when a configured ceiling is breached."""

    def __init__(self, config: BudgetConfig) -> None:
        """Start a guard at zero spend against ``config``'s ceilings."""
        self._config = config
        self._spent = CostRecord()

    @property
    def spent(self) -> CostRecord:
        """The total cost recorded against this run so far."""
        return self._spent

    @property
    def stop_at_stage_boundary(self) -> bool:
        """Whether a breach should let the current stage finish before stopping.

        Surfaced from config so the stage loop can decide, when a ceiling is hit
        mid-stage, whether to stop after the current record or run the stage to
        completion and let the orchestrator stop at the boundary.
        """
        return self._config.stop_at_stage_boundary

    def record(self, cost: CostRecord) -> None:
        """Add ``cost`` to the running total. A no-op in effect when ceilings are off.

        The total is still accumulated when enforcement is disabled — it costs
        nothing and keeps the run report's spend figure honest — but
        :meth:`first_breach` always returns ``None`` while disabled.
        """
        self._spent = self._spent.plus(cost)

    def first_breach(self) -> str | None:
        """Return a description of the first ceiling exceeded, or ``None``.

        Checked after each record and between stages. Returns ``None`` when
        enforcement is disabled or every unit is within its ceiling; otherwise a
        human-readable string naming the ceiling and the numbers, suitable for
        the run report and the logs.
        """
        if not self._config.enabled:
            return None
        checks = (
            ("crawls", self._spent.crawls, self._config.max_crawls_per_run),
            ("searches", self._spent.searches, self._config.max_searches_per_run),
            ("LLM calls", self._spent.llm_calls, self._config.max_llm_calls_per_run),
        )
        for label, spent, ceiling in checks:
            if spent > ceiling:
                return f"{label} ceiling exceeded: {spent} > {ceiling}"
        return None

    @property
    def exceeded(self) -> bool:
        """Whether any enforced ceiling has been breached."""
        return self.first_breach() is not None
