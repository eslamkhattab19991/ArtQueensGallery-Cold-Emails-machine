"""Tests for the orchestrator: sequencing, chain validation, resume, budget stop.

Driven by stub stages, since the concrete stages come later. A ``CountingSource``
generates the initial records; ``PassThrough`` stages advance them unchanged. The
point is the conductor's behaviour, not any stage's logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prospecting.config.loader import load_settings, resolve_project_root
from prospecting.config.models.settings import Settings
from prospecting.domain.identifiers import RunId
from prospecting.pipeline.base import (
    ProcessResult,
    RecordStage,
    Stage,
    StageContext,
    StageReport,
)
from prospecting.pipeline.orchestrator import (
    Orchestrator,
    PipelineConfigurationError,
)
from prospecting.schemas.envelope import CostRecord, StageEnvelope, StageName
from prospecting.schemas.seed import SeedOrganization
from tests.support.stores import InMemoryStageStore

RUN_ID = RunId("run_test")


def _settings(tmp_path: Path, **env: str) -> Settings:
    """Real shipped config, but with all data paths isolated under tmp_path."""
    return load_settings(
        config_dir=resolve_project_root() / "config",
        environ=env,
        project_root=tmp_path,
    )


def _seed(name: str) -> SeedOrganization:
    return SeedOrganization(row_number=2, name=name, website="https://example.com")


class CountingSource:
    """A source stage that emits a fixed number of records at a fixed cost."""

    name = StageName.INPUT
    reads: StageName | None = None

    def __init__(self, count: int, cost: CostRecord | None = None) -> None:
        """Emit ``count`` records, charging ``cost`` once to the run budget."""
        self._count = count
        self._cost = cost or CostRecord()

    def run(self, context: StageContext) -> StageReport:
        """Generate the initial records and record them as done."""
        envelopes = [
            StageEnvelope.create(
                record_id=f"in-{index}",
                run_id=context.run_id,
                stage=StageName.INPUT,
                payload=_seed(f"org-{index}"),
            )
            for index in range(self._count)
        ]
        context.store.append(StageName.INPUT, envelopes)
        for envelope in envelopes:
            context.checkpoint.mark_done(envelope.record_id)
        context.budget.record(self._cost)
        context.checkpoint.mark_stage_complete()
        return StageReport(
            stage=StageName.INPUT, processed=self._count, emitted=self._count, complete=True
        )


class PassThrough(RecordStage[SeedOrganization, SeedOrganization]):
    """A record stage that advances each record unchanged."""

    input_type = SeedOrganization

    def __init__(self, *, name: StageName, reads: StageName) -> None:
        """Run as ``name``, reading the output of ``reads``."""
        self.name = name
        self.reads = reads

    def process_record(
        self, envelope: StageEnvelope[SeedOrganization], context: StageContext
    ) -> ProcessResult[SeedOrganization]:
        del context
        return ProcessResult(outputs=(envelope.advance(stage=self.name, payload=envelope.payload),))


def _linear_pipeline() -> list[Stage]:
    """A source feeding two pass-through stages: INPUT -> DISCOVERY -> EXTRACTION."""
    return [
        CountingSource(count=3),
        PassThrough(name=StageName.DISCOVERY, reads=StageName.INPUT),
        PassThrough(name=StageName.EXTRACTION, reads=StageName.DISCOVERY),
    ]


class TestSequencing:
    def test_runs_every_stage_in_order(self, tmp_path: Path) -> None:
        store = InMemoryStageStore()
        orchestrator = Orchestrator(
            stages=_linear_pipeline(),
            settings=_settings(tmp_path),
            store=store,
            run_id=RUN_ID,
        )
        report = orchestrator.run()
        assert report.all_stages_complete
        assert [stage_report.stage for stage_report in report.stages] == [
            StageName.INPUT,
            StageName.DISCOVERY,
            StageName.EXTRACTION,
        ]

    def test_records_flow_all_the_way_through(self, tmp_path: Path) -> None:
        store = InMemoryStageStore()
        Orchestrator(
            stages=_linear_pipeline(),
            settings=_settings(tmp_path),
            store=store,
            run_id=RUN_ID,
        ).run()
        assert len(list(store.read(StageName.EXTRACTION, SeedOrganization))) == 3


class TestChainValidation:
    def test_an_empty_pipeline_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PipelineConfigurationError, match="at least one stage"):
            Orchestrator(
                stages=[], settings=_settings(tmp_path), store=InMemoryStageStore(), run_id=RUN_ID
            )

    def test_the_first_stage_must_be_a_source(self, tmp_path: Path) -> None:
        with pytest.raises(PipelineConfigurationError, match="source that reads nothing"):
            Orchestrator(
                stages=[PassThrough(name=StageName.DISCOVERY, reads=StageName.INPUT)],
                settings=_settings(tmp_path),
                store=InMemoryStageStore(),
                run_id=RUN_ID,
            )

    def test_a_broken_read_chain_is_rejected(self, tmp_path: Path) -> None:
        stages: list[Stage] = [
            CountingSource(count=1),
            # Reads EXTRACTION, but follows INPUT — a gap in the chain.
            PassThrough(name=StageName.DISCOVERY, reads=StageName.EXTRACTION),
        ]
        with pytest.raises(PipelineConfigurationError, match="read-chain"):
            Orchestrator(
                stages=stages,
                settings=_settings(tmp_path),
                store=InMemoryStageStore(),
                run_id=RUN_ID,
            )


class TestResume:
    def test_a_second_run_skips_completed_stages(self, tmp_path: Path) -> None:
        store = InMemoryStageStore()
        settings = _settings(tmp_path)
        Orchestrator(
            stages=_linear_pipeline(),
            settings=settings,
            store=store,
            run_id=RUN_ID,
        ).run()

        second = Orchestrator(
            stages=_linear_pipeline(),
            settings=settings,
            store=store,
            run_id=RUN_ID,
        ).run()
        assert all(stage_report.already_complete for stage_report in second.stages)
        assert second.all_stages_complete

    def test_resume_disabled_reruns_everything(self, tmp_path: Path) -> None:
        store = InMemoryStageStore()
        settings = _settings(tmp_path)
        Orchestrator(
            stages=_linear_pipeline(),
            settings=settings,
            store=store,
            run_id=RUN_ID,
        ).run()

        fresh = Orchestrator(
            stages=_linear_pipeline(),
            settings=settings,
            store=store,
            run_id=RUN_ID,
            resume=False,
        ).run()
        assert not any(stage_report.already_complete for stage_report in fresh.stages)


class TestBudgetStop:
    def test_stops_before_the_next_stage_when_a_ceiling_is_breached(self, tmp_path: Path) -> None:
        store = InMemoryStageStore()
        settings = _settings(tmp_path, PROSPECTING__BUDGET__MAX_CRAWLS_PER_RUN="2")
        stages: list[Stage] = [
            CountingSource(count=1, cost=CostRecord(crawls=5)),
            PassThrough(name=StageName.DISCOVERY, reads=StageName.INPUT),
        ]
        report = Orchestrator(
            stages=stages,
            settings=settings,
            store=store,
            run_id=RUN_ID,
        ).run()
        assert report.stopped_by_budget
        assert report.budget_breach is not None
        assert not report.all_stages_complete
        # The source ran; the downstream stage never did.
        assert [stage_report.stage for stage_report in report.stages] == [StageName.INPUT]
        assert not store.has_stage(StageName.DISCOVERY)


class TestRunReport:
    def test_spend_is_totalled(self, tmp_path: Path) -> None:
        store = InMemoryStageStore()
        stages: list[Stage] = [
            CountingSource(count=1, cost=CostRecord(searches=4)),
            PassThrough(name=StageName.DISCOVERY, reads=StageName.INPUT),
        ]
        report = Orchestrator(
            stages=stages,
            settings=_settings(tmp_path),
            store=store,
            run_id=RUN_ID,
        ).run()
        assert report.spent.searches == 4
