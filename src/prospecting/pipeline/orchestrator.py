"""The orchestrator: run the stages in order, resume, and stop within budget.

ARCHITECTURE.md §7 — ``pipeline/orchestrator``: "Sequence stages, resume, enforce
budget", and explicitly *not* contain stage logic. It is the conductor. It knows
the order of the stages and nothing about what any of them does; each stage reads
its input and writes its output through the store, so the orchestrator only has
to decide *whether* and *when* to run each one.

Its three jobs, and where each lives:

* **Sequence.** It validates at construction that the stages form a chain — the
  first is a source (reads nothing), each later one reads the stage before it —
  so a misordered pipeline fails at startup, not with an empty read halfway
  through a paid run.
* **Resume.** Each stage gets its own checkpoint. A stage already marked complete
  on a previous run is skipped whole; a stage left part-way resumes record by
  record (that finer resume lives in :class:`~prospecting.pipeline.base.RecordStage`).
* **Budget.** One :class:`~prospecting.pipeline.budget.BudgetGuard` spans the run.
  The orchestrator checks it between stages and stops cleanly at the boundary
  when a ceiling is breached; a stage may also stop itself mid-way. Either way the
  run halts at a resumable point rather than aborting (BudgetConfig docstring).

The gate is not re-implemented here. The qualification precondition is enforced
per record inside :class:`RecordStage`, which raises if a stage is handed a
record it does not admit — the orchestrator lets that failure propagate, because
a broken gate is a bug to surface, not to absorb.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from prospecting.config.models.settings import Settings
from prospecting.domain.identifiers import RunId
from prospecting.pipeline.base import Stage, StageContext, StageReport
from prospecting.pipeline.budget import BudgetGuard
from prospecting.pipeline.checkpoint import CheckpointManager
from prospecting.ports.stage_store import StageStore
from prospecting.schemas.envelope import CostRecord

__all__ = ["Orchestrator", "PipelineConfigurationError", "RunReport"]


class PipelineConfigurationError(Exception):
    """The stages do not form a valid pipeline.

    Raised at construction — before any work runs — when the stages are empty,
    do not start with a source, or are not a read-chain. Catching this at startup
    is the difference between a clear "stage X reads Y but follows Z" message and
    a stage silently reading an empty input an hour into a run.
    """


@dataclass(frozen=True, slots=True)
class RunReport:
    """The outcome of one orchestrated run, for the run ledger and the logs.

    Mechanical diagnostics — per-stage counts, total spend, why it stopped. The
    KPI-led ``statistics.json`` (ARCHITECTURE.md §4.8) is the export stage's job;
    it reads these counts but leads with completed leads, which only exist once
    that stage has run.
    """

    run_id: RunId
    stages: tuple[StageReport, ...] = ()
    spent: CostRecord = field(default_factory=CostRecord)
    stopped_by_budget: bool = False
    budget_breach: str | None = None

    @property
    def all_stages_complete(self) -> bool:
        """Whether every stage ran to completion and nothing stopped the run."""
        return not self.stopped_by_budget and all(report.complete for report in self.stages)


class Orchestrator:
    """Run a fixed sequence of stages for one pipeline execution."""

    def __init__(
        self,
        *,
        stages: Sequence[Stage],
        settings: Settings,
        store: StageStore,
        run_id: RunId,
        resume: bool | None = None,
    ) -> None:
        """Assemble a run over ``stages`` and validate that they form a chain.

        Args:
            stages: The stages, in execution order. The first must be a source
                (``reads is None``); each later stage must read the one before it.
            settings: The run's configuration — checkpoint cadence, budget
                ceilings, and the paths the checkpoints live under.
            store: The stage store the stages read from and write to.
            run_id: Identifier for this execution, namespacing its checkpoints.
            resume: Override for the configured resume-by-default. ``None`` uses
                the configured default; ``False`` starts every stage fresh.

        Raises:
            PipelineConfigurationError: The stages are empty, do not start with a
                source, or are not a valid read-chain.
        """
        self._stages = tuple(stages)
        self._settings = settings
        self._store = store
        self._run_id = run_id
        self._resume = resume
        self._validate_chain()

    def _validate_chain(self) -> None:
        """Fail unless the stages form a source-led read-chain."""
        if not self._stages:
            message = "a pipeline needs at least one stage."
            raise PipelineConfigurationError(message)

        first = self._stages[0]
        if first.reads is not None:
            message = (
                f"the first stage must be a source that reads nothing, but "
                f"{first.name.value!r} reads {first.reads.value!r}."
            )
            raise PipelineConfigurationError(message)

        for previous, current in zip(self._stages, self._stages[1:], strict=False):
            if current.reads != previous.name:
                reads = current.reads.value if current.reads is not None else None
                message = (
                    f"stage {current.name.value!r} reads {reads!r} but follows "
                    f"{previous.name.value!r}; stages must form a read-chain."
                )
                raise PipelineConfigurationError(message)

    def run(self) -> RunReport:
        """Run each stage in order until they finish or a ceiling stops the run."""
        budget = BudgetGuard(self._settings.budget)
        checkpoint_root = self._settings.paths.checkpoints_for_run(self._run_id)
        reports: list[StageReport] = []
        stopped_by_budget = False

        for stage in self._stages:
            if budget.exceeded:
                stopped_by_budget = True
                break

            checkpoint = CheckpointManager(
                stage=stage.name,
                directory=checkpoint_root,
                config=self._settings.checkpoint,
                resume=self._resume,
            )
            if checkpoint.is_stage_complete():
                reports.append(StageReport(stage=stage.name, complete=True, already_complete=True))
                continue

            context = StageContext(
                run_id=self._run_id,
                settings=self._settings,
                store=self._store,
                checkpoint=checkpoint,
                budget=budget,
            )
            with checkpoint:
                report = stage.run(context)
            reports.append(report)

            if report.stopped_by_budget:
                stopped_by_budget = True
                break

        return RunReport(
            run_id=self._run_id,
            stages=tuple(reports),
            spent=budget.spent,
            stopped_by_budget=stopped_by_budget,
            budget_breach=budget.first_breach(),
        )
