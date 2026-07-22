"""Per-run spending ceilings."""

from __future__ import annotations

from pydantic import Field

from prospecting.config.models.base import FrozenConfig

__all__ = ["BudgetConfig"]


class BudgetConfig(FrozenConfig):
    """Hard ceilings that stop a run before it exhausts a provider balance.

    ARCHITECTURE.md §9 calls for budget caps enforced between stages. Ceilings
    are expressed both in money and in provider units because the two fail
    differently: a currency ceiling protects the account, while unit ceilings
    catch a runaway query expansion long before it becomes expensive.

    Exceeding a ceiling stops the run at a resumable checkpoint rather than
    aborting, so the work already paid for is never lost.
    """

    enabled: bool = Field(description="Whether ceilings are enforced at all.")
    max_usd_per_run: float = Field(
        gt=0.0, description="Total estimated spend across every provider in one run."
    )
    max_crawls_per_run: int = Field(ge=1, description="Ceiling on page fetches.")
    max_searches_per_run: int = Field(ge=1, description="Ceiling on search-provider queries.")
    max_llm_calls_per_run: int = Field(ge=1, description="Ceiling on model invocations.")
    stop_at_stage_boundary: bool = Field(
        description="Stop cleanly between stages rather than mid-stage when a ceiling is hit."
    )
