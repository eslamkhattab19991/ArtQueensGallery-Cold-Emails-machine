"""Tests for the run-level budget guard.

The guard's job is to answer one question honestly — has this run breached a
ceiling? — so a run stops before it drains a provider balance rather than after.
"""

from __future__ import annotations

from prospecting.config.models.budget import BudgetConfig
from prospecting.pipeline.budget import BudgetGuard
from prospecting.schemas.envelope import CostRecord


def make_config(**overrides: object) -> BudgetConfig:
    values: dict[str, object] = {
        "enabled": True,
        "max_usd_per_run": 25.0,
        "max_crawls_per_run": 10,
        "max_searches_per_run": 5,
        "max_llm_calls_per_run": 8,
        "stop_at_stage_boundary": True,
    }
    values.update(overrides)
    return BudgetConfig(**values)


class TestAccumulation:
    def test_starts_at_zero(self) -> None:
        assert BudgetGuard(make_config()).spent.is_zero

    def test_records_sum_across_calls(self) -> None:
        guard = BudgetGuard(make_config())
        guard.record(CostRecord(crawls=2))
        guard.record(CostRecord(crawls=3, searches=1))
        assert guard.spent.crawls == 5
        assert guard.spent.searches == 1


class TestCeilings:
    def test_within_every_ceiling_is_not_a_breach(self) -> None:
        guard = BudgetGuard(make_config(max_crawls_per_run=10))
        guard.record(CostRecord(crawls=10))  # exactly at the ceiling is allowed
        assert guard.first_breach() is None
        assert not guard.exceeded

    def test_crawls_over_the_ceiling_breach(self) -> None:
        guard = BudgetGuard(make_config(max_crawls_per_run=3))
        guard.record(CostRecord(crawls=4))
        assert guard.exceeded
        assert "crawls" in (guard.first_breach() or "")

    def test_searches_over_the_ceiling_breach(self) -> None:
        guard = BudgetGuard(make_config(max_searches_per_run=2))
        guard.record(CostRecord(searches=3))
        assert "searches" in (guard.first_breach() or "")

    def test_llm_calls_over_the_ceiling_breach(self) -> None:
        guard = BudgetGuard(make_config(max_llm_calls_per_run=1))
        guard.record(CostRecord(llm_calls=2))
        assert "LLM calls" in (guard.first_breach() or "")

    def test_the_breach_message_names_the_numbers(self) -> None:
        guard = BudgetGuard(make_config(max_crawls_per_run=3))
        guard.record(CostRecord(crawls=5))
        breach = guard.first_breach() or ""
        assert "5" in breach
        assert "3" in breach


class TestDisabled:
    def test_disabled_ceilings_never_breach(self) -> None:
        guard = BudgetGuard(make_config(enabled=False, max_crawls_per_run=1))
        guard.record(CostRecord(crawls=1000))
        assert guard.first_breach() is None
        assert not guard.exceeded

    def test_spend_is_still_tracked_when_disabled(self) -> None:
        """The report's spend figure stays honest even without enforcement."""
        guard = BudgetGuard(make_config(enabled=False))
        guard.record(CostRecord(crawls=1000))
        assert guard.spent.crawls == 1000


class TestStopBoundaryPassthrough:
    def test_reflects_the_configured_boundary_policy(self) -> None:
        assert BudgetGuard(make_config(stop_at_stage_boundary=True)).stop_at_stage_boundary
        assert not BudgetGuard(make_config(stop_at_stage_boundary=False)).stop_at_stage_boundary
