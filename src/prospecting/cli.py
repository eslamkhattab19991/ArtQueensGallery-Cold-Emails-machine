"""The ``prospect`` command line: inspect configuration and run the pipeline.

The operator-facing surface. It does no work of its own — it loads settings,
turns logging on, asks the composition root to assemble the run, and hands off to
the orchestrator — so the command layer stays a thin translation of arguments
into the calls the rest of the system already exposes.
"""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime
from typing import Annotated

import typer

from prospecting.config.container import build_pipeline_stages, build_stage_store
from prospecting.config.errors import ConfigError
from prospecting.config.loader import load_settings
from prospecting.config.models.settings import Settings
from prospecting.domain.identifiers import RunId
from prospecting.observability.logger import configure_logging
from prospecting.pipeline.orchestrator import Orchestrator, RunReport

__all__ = ["app", "main"]

#: The installed distribution name, for reporting the version.
_DISTRIBUTION = "artqueens-prospecting"

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Art Queens Gallery — artist prospecting pipeline.",
)

_ProfileOption = Annotated[
    str | None,
    typer.Option("--profile", "-p", help="Configuration profile overlay to apply (e.g. dev)."),
]


def _generate_run_id() -> RunId:
    """Mint a fresh, sortable run id from the current UTC time."""
    return RunId(f"run_{datetime.now(UTC):%Y-%m-%d_%H%M%S}")


def _load_or_exit(profile: str | None) -> Settings:
    """Load settings, printing every configuration problem and exiting on failure."""
    try:
        return load_settings(profile=profile)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(importlib.metadata.version(_DISTRIBUTION))


@app.command()
def config(profile: _ProfileOption = None) -> None:
    """Load, validate, and print the resolved configuration and its provenance.

    Validation is a side effect worth having on its own: this is how an operator
    checks that an edit to ``config/*.yaml`` is well-formed before committing to a
    run, with every problem reported at once rather than one API call in.
    """
    settings = _load_or_exit(profile)
    typer.echo(settings.model_dump_json(indent=2))


@app.command()
def run(
    profile: _ProfileOption = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Resume a specific run id, or omit to start a new run."),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume/--no-resume", help="Resume from checkpoints, or start fresh."),
    ] = True,
) -> None:
    """Run the prospecting pipeline for one execution."""
    settings = _load_or_exit(profile)
    configure_logging(settings.log)

    resolved_run_id = RunId(run_id) if run_id else _generate_run_id()
    stages = build_pipeline_stages(settings)
    if not stages:
        typer.echo(
            "No pipeline stages are wired yet — they arrive with the providers "
            "(see README). Nothing to run.",
            err=True,
        )
        raise typer.Exit(code=1)

    store = build_stage_store(settings, resolved_run_id)
    orchestrator = Orchestrator(
        stages=stages, settings=settings, store=store, run_id=resolved_run_id, resume=resume
    )
    _print_report(orchestrator.run())


def _print_report(report: RunReport) -> None:
    """Print a short, human-readable summary of a finished run."""
    typer.echo(f"run {report.run_id}: {'complete' if report.all_stages_complete else 'incomplete'}")
    for stage_report in report.stages:
        typer.echo(
            f"  {stage_report.stage.value:<18} "
            f"processed={stage_report.processed} skipped={stage_report.skipped} "
            f"failed={stage_report.failed}"
        )
    if report.stopped_by_budget:
        typer.echo(f"stopped: {report.budget_breach}", err=True)


def main() -> None:
    """Console-script entry point for the ``prospect`` command."""
    app()


if __name__ == "__main__":
    main()
