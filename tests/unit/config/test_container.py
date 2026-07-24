"""Tests for the composition root.

Thin by design, so the tests are too: the store it builds writes where the run's
interim directory says, and the stage list is honestly empty until the providers
land.
"""

from __future__ import annotations

from pathlib import Path

from prospecting.config.container import build_pipeline_stages, build_stage_store
from prospecting.config.loader import load_settings, resolve_project_root
from prospecting.config.models.settings import Settings
from prospecting.domain.identifiers import RunId
from prospecting.schemas.envelope import StageEnvelope, StageName
from prospecting.schemas.seed import SeedOrganization


def _settings(tmp_path: Path) -> Settings:
    return load_settings(
        config_dir=resolve_project_root() / "config", environ={}, project_root=tmp_path
    )


def test_build_stage_store_writes_under_the_runs_interim_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    run_id = RunId("run_abc")
    store = build_stage_store(settings, run_id)
    store.append(
        StageName.INPUT,
        [
            StageEnvelope.create(
                record_id="r1",
                run_id=run_id,
                stage=StageName.INPUT,
                payload=SeedOrganization(row_number=2, name="Alpha", website="https://x.com"),
            )
        ],
    )
    assert (settings.paths.interim_for_run(run_id) / "input.jsonl").is_file()


def test_pipeline_stages_are_empty_until_the_providers_land(tmp_path: Path) -> None:
    assert build_pipeline_stages(_settings(tmp_path)) == []
