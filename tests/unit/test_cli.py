"""Tests for the ``prospect`` command line.

The CLI is thin glue, so these check the glue: the version prints, the config
command loads and validates, a bad profile fails loudly, and ``run`` reports
honestly that no stages are wired yet rather than pretending to work.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from prospecting.cli import _print_report, app
from prospecting.config.loader import load_settings, resolve_project_root
from prospecting.domain.identifiers import RunId
from prospecting.pipeline.base import StageContext, StageReport
from prospecting.pipeline.orchestrator import RunReport
from prospecting.schemas.envelope import StageName
from tests.support.stores import InMemoryStageStore

runner = CliRunner()


class _NullSource:
    """A source stage that completes immediately, for exercising the run wiring."""

    name = StageName.INPUT
    reads: StageName | None = None

    def run(self, context: StageContext) -> StageReport:
        """Mark the stage complete without emitting anything."""
        context.checkpoint.mark_stage_complete()
        return StageReport(stage=StageName.INPUT, complete=True)


class TestVersion:
    def test_prints_the_installed_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "0.1.0"


class TestConfig:
    def test_prints_the_resolved_configuration(self) -> None:
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert '"rubric_version"' in result.stdout

    def test_a_missing_profile_fails_loudly(self) -> None:
        result = runner.invoke(app, ["config", "--profile", "does-not-exist"])
        assert result.exit_code == 1
        assert "does-not-exist" in result.stderr


class TestRun:
    def test_reports_that_no_stages_are_wired_yet(self) -> None:
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1
        assert "No pipeline stages are wired yet" in result.stderr

    def test_runs_and_reports_when_stages_are_wired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The happy path: settings load, logging turns on, the run completes.

        The stages and store are substituted so the command's wiring is exercised
        end to end without a real pipeline or touching the project's data dir.
        """
        settings = load_settings(
            config_dir=resolve_project_root() / "config", environ={}, project_root=tmp_path
        )
        monkeypatch.setattr("prospecting.cli.load_settings", lambda **_: settings)
        monkeypatch.setattr("prospecting.cli.build_pipeline_stages", lambda _: [_NullSource()])
        monkeypatch.setattr("prospecting.cli.build_stage_store", lambda *_: InMemoryStageStore())

        result = runner.invoke(app, ["run"])
        assert result.exit_code == 0
        assert "complete" in result.stdout
        assert "input" in result.stdout


class TestReport:
    def test_a_budget_stop_is_surfaced(self, capsys: pytest.CaptureFixture[str]) -> None:
        _print_report(
            RunReport(
                run_id=RunId("run_x"),
                stages=(StageReport(stage=StageName.INPUT),),
                stopped_by_budget=True,
                budget_breach="crawls ceiling exceeded: 5 > 2",
            )
        )
        assert "stopped" in capsys.readouterr().err


class TestHelp:
    def test_no_arguments_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # no_args_is_help exits with the help screen rather than an error.
        assert "prospecting pipeline" in result.stdout
