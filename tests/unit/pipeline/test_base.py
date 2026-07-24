"""Tests for the shared record-processing loop (RecordStage).

The loop is where three cross-cutting guarantees live, so they are tested here
once rather than in every future stage: resumability (done records are skipped),
the absolute qualification gate (an inadmissible record stops the run), and
budget stopping (a breached ceiling halts at a resumable point). Failure
isolation — one bad record not killing its siblings — is tested alongside.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from prospecting.config.loader import load_settings
from prospecting.config.models.budget import BudgetConfig
from prospecting.config.models.checkpoint import CheckpointConfig
from prospecting.config.models.settings import Settings
from prospecting.domain.identifiers import RunId
from prospecting.observability.logger import configure_logging
from prospecting.pipeline.base import (
    PreconditionError,
    ProcessResult,
    RecordStage,
    StageContext,
)
from prospecting.pipeline.budget import BudgetGuard
from prospecting.pipeline.checkpoint import CheckpointManager
from prospecting.schemas.envelope import CostRecord, StageEnvelope, StageName
from prospecting.schemas.seed import SeedOrganization
from tests.support.stores import InMemoryStageStore

RUN_ID = RunId("run_test")


def _settings() -> Settings:
    return load_settings(environ={})


def _checkpoint_config(**overrides: object) -> CheckpointConfig:
    values: dict[str, object] = {
        "enabled": True,
        "flush_every_n_records": 1,
        "resume_by_default": True,
        "record_failures_separately": True,
        "checkpoint_filename": "checkpoint.json",
        "failure_filename": "failures.jsonl",
    }
    values.update(overrides)
    return CheckpointConfig(**values)


def _budget_config(**overrides: object) -> BudgetConfig:
    values: dict[str, object] = {
        "enabled": True,
        "max_usd_per_run": 25.0,
        "max_crawls_per_run": 1000,
        "max_searches_per_run": 1000,
        "max_llm_calls_per_run": 1000,
        "stop_at_stage_boundary": True,
    }
    values.update(overrides)
    return BudgetConfig(**values)


def _seed(name: str) -> SeedOrganization:
    return SeedOrganization(row_number=2, name=name, website="https://example.com")


def _seed_inputs(store: InMemoryStageStore, names: list[str]) -> None:
    """Write ACTIVE input-stage envelopes for the given names."""
    envelopes = [
        StageEnvelope.create(
            record_id=f"rec-{index}", run_id=RUN_ID, stage=StageName.INPUT, payload=_seed(name)
        )
        for index, name in enumerate(names)
    ]
    store.append(StageName.INPUT, envelopes)


def _context(
    store: InMemoryStageStore,
    checkpoint: CheckpointManager,
    *,
    budget: BudgetGuard | None = None,
    settings: Settings,
) -> StageContext:
    return StageContext(
        run_id=RUN_ID,
        settings=settings,
        store=store,
        checkpoint=checkpoint,
        budget=budget or BudgetGuard(_budget_config()),
    )


class EchoStage(RecordStage[SeedOrganization, SeedOrganization]):
    """A trivial stage that advances each record unchanged, at a fixed cost."""

    name = StageName.DISCOVERY
    reads = StageName.INPUT
    input_type = SeedOrganization

    def __init__(self, cost: CostRecord | None = None) -> None:
        """Record the fixed per-record cost this stub reports to the budget."""
        self._cost = cost or CostRecord()

    def process_record(
        self, envelope: StageEnvelope[SeedOrganization], context: StageContext
    ) -> ProcessResult[SeedOrganization]:
        del context
        output = envelope.advance(stage=self.name, payload=envelope.payload)
        return ProcessResult(outputs=(output,), cost=self._cost)


class FailingStage(EchoStage):
    """Raises on any record named 'bad', to exercise failure isolation."""

    def process_record(
        self, envelope: StageEnvelope[SeedOrganization], context: StageContext
    ) -> ProcessResult[SeedOrganization]:
        if envelope.payload.name == "bad":
            message = "boom"
            raise RuntimeError(message)
        return super().process_record(envelope, context)


class GatedStage(EchoStage):
    """Admits every record except one named 'forbidden'."""

    def admits(self, envelope: StageEnvelope[SeedOrganization]) -> bool:
        return envelope.payload.name != "forbidden"


@pytest.fixture(scope="module")
def settings() -> Settings:
    return _settings()


class TestTransformation:
    def test_processes_every_active_record(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["A", "B"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        report = EchoStage().run(_context(store, checkpoint, settings=settings))
        assert (report.processed, report.emitted, report.skipped, report.failed) == (2, 2, 0, 0)
        assert report.complete
        assert store.has_stage(StageName.DISCOVERY)

    def test_outputs_carry_lineage_forward(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["A"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        EchoStage().run(_context(store, checkpoint, settings=settings))
        outputs = list(store.read(StageName.DISCOVERY, SeedOrganization))
        assert outputs[0].stage is StageName.DISCOVERY
        assert outputs[0].lineage == (StageName.INPUT,)

    def test_terminal_records_do_not_advance(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        active = StageEnvelope.create(
            record_id="rec-0", run_id=RUN_ID, stage=StageName.INPUT, payload=_seed("keep")
        )
        rejected = StageEnvelope.create(
            record_id="rec-1", run_id=RUN_ID, stage=StageName.INPUT, payload=_seed("drop")
        ).reject("not qualified")
        store.append(StageName.INPUT, [active, rejected])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        report = EchoStage().run(_context(store, checkpoint, settings=settings))
        assert report.processed == 1
        assert len(list(store.read(StageName.DISCOVERY, SeedOrganization))) == 1


class TestResumability:
    def test_already_done_records_are_skipped(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["A", "B"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        checkpoint.mark_done("rec-0")
        report = EchoStage().run(_context(store, checkpoint, settings=settings))
        assert report.skipped == 1
        assert report.processed == 1

    def test_a_completed_stage_is_marked_complete(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["A"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        EchoStage().run(_context(store, checkpoint, settings=settings))
        resumed = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        assert resumed.is_stage_complete()

    def test_an_empty_stage_still_completes(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        report = EchoStage().run(_context(store, checkpoint, settings=settings))
        assert report.processed == 0
        assert report.complete


class TestQualificationGate:
    def test_an_inadmissible_record_stops_the_run(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["ok", "forbidden"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        with pytest.raises(PreconditionError, match="does not admit"):
            GatedStage().run(_context(store, checkpoint, settings=settings))

    def test_admitted_records_pass_through(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["ok1", "ok2"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        report = GatedStage().run(_context(store, checkpoint, settings=settings))
        assert report.processed == 2


class TestFailureIsolation:
    def test_one_failure_does_not_stop_the_others(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["good", "bad", "good2"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        report = FailingStage().run(_context(store, checkpoint, settings=settings))
        assert report.processed == 2
        assert report.failed == 1
        assert checkpoint.failure_count == 1

    def test_a_failed_record_is_not_marked_done(self, tmp_path: Path, settings: Settings) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["bad"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        FailingStage().run(_context(store, checkpoint, settings=settings))
        assert not checkpoint.is_done("rec-0")


class TestBudgetStopping:
    def test_stops_mid_stage_when_boundary_stopping_is_off(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["A", "B", "C", "D"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        budget = BudgetGuard(_budget_config(max_crawls_per_run=2, stop_at_stage_boundary=False))
        report = EchoStage(cost=CostRecord(crawls=1)).run(
            _context(store, checkpoint, budget=budget, settings=settings)
        )
        assert report.stopped_by_budget
        assert not report.complete
        assert report.processed < 4

    def test_a_budget_stopped_stage_is_not_marked_complete(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["A", "B", "C", "D"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        budget = BudgetGuard(_budget_config(max_crawls_per_run=1, stop_at_stage_boundary=False))
        EchoStage(cost=CostRecord(crawls=1)).run(
            _context(store, checkpoint, budget=budget, settings=settings)
        )
        resumed = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        assert not resumed.is_stage_complete()

    def test_boundary_stopping_lets_the_stage_finish(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        store = InMemoryStageStore()
        _seed_inputs(store, ["A", "B", "C"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        budget = BudgetGuard(_budget_config(max_crawls_per_run=1, stop_at_stage_boundary=True))
        report = EchoStage(cost=CostRecord(crawls=1)).run(
            _context(store, checkpoint, budget=budget, settings=settings)
        )
        assert report.complete
        assert report.processed == 3
        assert budget.exceeded


class TestProcessResult:
    def test_defaults_to_no_output_and_zero_cost(self) -> None:
        result: ProcessResult[SeedOrganization] = ProcessResult()
        assert result.outputs == ()
        assert result.cost.is_zero


class TestProgressLogging:
    def test_logs_progress_at_the_configured_cadence_with_running_cost(
        self, tmp_path: Path
    ) -> None:
        settings = load_settings(
            environ={
                "PROSPECTING__LOG__FORMAT": "json",
                "PROSPECTING__LOG__LEVEL": "INFO",
                "PROSPECTING__LOG__PROGRESS_EVERY_N_RECORDS": "1",
                "PROSPECTING__LOG__LOG_COST_ESTIMATES": "true",
            }
        )
        buffer = StringIO()
        configure_logging(settings.log, stream=buffer)

        store = InMemoryStageStore()
        _seed_inputs(store, ["A", "B"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        EchoStage(cost=CostRecord(crawls=1)).run(_context(store, checkpoint, settings=settings))

        progress = [
            parsed
            for line in buffer.getvalue().splitlines()
            if line.strip()
            for parsed in [json.loads(line)]
            if parsed["message"] == "progress"
        ]
        assert len(progress) == 2
        # Running spend accumulates across the two records.
        assert progress[0]["crawls"] == 1
        assert progress[1]["crawls"] == 2

    def test_progress_omits_cost_when_estimates_are_off(self, tmp_path: Path) -> None:
        settings = load_settings(
            environ={
                "PROSPECTING__LOG__FORMAT": "json",
                "PROSPECTING__LOG__LEVEL": "INFO",
                "PROSPECTING__LOG__PROGRESS_EVERY_N_RECORDS": "1",
                "PROSPECTING__LOG__LOG_COST_ESTIMATES": "false",
            }
        )
        buffer = StringIO()
        configure_logging(settings.log, stream=buffer)

        store = InMemoryStageStore()
        _seed_inputs(store, ["A"])
        checkpoint = CheckpointManager(
            stage=StageName.DISCOVERY, directory=tmp_path, config=_checkpoint_config()
        )
        EchoStage(cost=CostRecord(crawls=1)).run(_context(store, checkpoint, settings=settings))

        progress = next(
            json.loads(line)
            for line in buffer.getvalue().splitlines()
            if line.strip() and json.loads(line)["message"] == "progress"
        )
        assert "crawls" not in progress
