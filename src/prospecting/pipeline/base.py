"""The stage contract and the record-processing loop every stage shares.

A stage is one transformation with one input shape and one output shape
(ARCHITECTURE.md §7). Stages never call each other; they read the previous
stage's output and write their own, both through the :class:`StageStore` port, so
the orchestrator can sequence, resume, and budget them without knowing what any
of them does.

Most stages are the same shape underneath: read each record of the prior stage's
output, skip the ones already done, transform the rest, write the results, and
record progress. :class:`RecordStage` implements that loop once so a concrete
stage writes only its :meth:`~RecordStage.process_record` transformation. Three
cross-cutting guarantees live in the loop, not in each stage:

* **Resumability.** A record already marked done in the checkpoint is skipped, so
  a resumed run never re-pays for finished work (Design Principle #3).
* **The absolute qualification gate.** Before a stage sees a record, the loop
  checks the stage *admits* it. A stage that does not admit a record it is handed
  fails the run loudly (:class:`PreconditionError`) — it is never called with a
  record it should not process. This is ARCHITECTURE.md §4.5.0 enforced by the
  engine as a precondition, not by the stage "declining to act".
* **Budget.** Each record's cost is recorded against the run guard; when a
  ceiling is breached the loop stops at a resumable point.

Failures are values, not aborts: a record whose transformation raises is logged
to the failure queue and skipped, never allowed to kill the run or its siblings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from prospecting.config.models.settings import Settings
from prospecting.domain.base import FrozenModel
from prospecting.domain.identifiers import RunId
from prospecting.pipeline.budget import BudgetGuard
from prospecting.pipeline.checkpoint import CheckpointManager
from prospecting.ports.stage_store import StageStore
from prospecting.schemas.envelope import CostRecord, RecordStatus, StageEnvelope, StageName

__all__ = [
    "PreconditionError",
    "ProcessResult",
    "RecordStage",
    "Stage",
    "StageContext",
    "StageReport",
]


class PreconditionError(Exception):
    """A stage was handed a record it does not admit — the gate failing loudly.

    ARCHITECTURE.md §4.5.0: "A stage that can be called with an unqualified artist
    and merely declines to act is one refactor away from acting." So an
    inadmissible record is not silently skipped; it stops the run, because its
    presence means an earlier gate is broken and the fix belongs upstream.
    """


@dataclass(frozen=True, slots=True)
class StageContext:
    """Everything a stage needs to run, handed to it by the orchestrator.

    Deliberately the run's *orchestration* services — where to read and write,
    what has been done, what has been spent — not the capability ports (crawler,
    LLM, …). A concrete stage is constructed with the specific ports it needs by
    the composition root; bundling every port here would undo the Interface
    Segregation the ports exist to provide.
    """

    run_id: RunId
    settings: Settings
    store: StageStore
    checkpoint: CheckpointManager
    budget: BudgetGuard


@runtime_checkable
class Stage(Protocol):
    """What the orchestrator sees of any stage: its identity and how to run it.

    A narrow contract so the orchestrator can sequence a heterogeneous pipeline —
    the record-transforming stages (:class:`RecordStage`) plus the source stage
    that generates the initial work items and the sink stage that writes the
    export files — without knowing which kind each one is. ``reads`` is the stage
    whose output feeds this one, or ``None`` for the pipeline's entry stage.
    """

    @property
    def name(self) -> StageName:
        """Which stage this is."""
        ...

    @property
    def reads(self) -> StageName | None:
        """The stage whose output this one consumes, or None for the entry stage."""
        ...

    def run(self, context: StageContext) -> StageReport:
        """Execute the stage against ``context`` and report what it did."""
        ...


@dataclass(frozen=True, slots=True)
class StageReport:
    """What one stage did, for the run report and the logs."""

    stage: StageName
    processed: int = 0
    emitted: int = 0
    skipped: int = 0
    failed: int = 0
    complete: bool = True
    stopped_by_budget: bool = False
    already_complete: bool = False


@dataclass(frozen=True, slots=True)
class ProcessResult[OutputT: FrozenModel]:
    """The output of transforming one record: the envelopes it produced and cost.

    ``cost`` is the *incremental* spend this one transformation incurred, which is
    what the budget guard accumulates — distinct from each output envelope's own
    ``cost``, which is that record's running total across every stage so far.
    """

    outputs: tuple[StageEnvelope[OutputT], ...] = ()
    cost: CostRecord = field(default_factory=CostRecord)


class RecordStage[InputT: FrozenModel, OutputT: FrozenModel](ABC):
    """Base for a stage that transforms each record of the prior stage's output.

    A subclass sets :attr:`name` (the stage it is), :attr:`reads` (the stage whose
    output it consumes), and :attr:`input_type` (the payload type to read back),
    then implements :meth:`process_record`. The shared :meth:`run` supplies
    resumability, the qualification gate, budget stopping, and failure isolation.
    """

    name: StageName
    reads: StageName
    input_type: type[InputT]

    @abstractmethod
    def process_record(
        self, envelope: StageEnvelope[InputT], context: StageContext
    ) -> ProcessResult[OutputT]:
        """Transform one input record into its output envelopes and cost.

        Called only for records this stage admits and has not already completed.
        Implementations build outputs with ``envelope.advance(...)`` so lineage
        and the running cost total carry forward.
        """

    def admits(self, envelope: StageEnvelope[InputT]) -> bool:
        """Whether this stage may process ``envelope`` — the precondition gate.

        The default admits any active record. A stage with an entry requirement
        overrides this: the contact-discovery stage, for instance, admits only
        qualified artists, so an unqualified record reaching it stops the run
        rather than being quietly contacted (ARCHITECTURE.md §4.5.0).
        """
        del envelope
        return True

    def run(self, context: StageContext) -> StageReport:
        """Process the prior stage's active records, with the shared guarantees."""
        processed = emitted = skipped = failed = 0
        stopped_by_budget = False

        for envelope in context.store.read(self.reads, self.input_type):
            if envelope.status is not RecordStatus.ACTIVE:
                continue  # terminal records (rejected, failed) do not advance.

            if not self.admits(envelope):
                message = (
                    f"stage {self.name.value!r} was handed record {envelope.record_id!r}, "
                    "which it does not admit. The qualification gate is failing loudly "
                    "(ARCHITECTURE.md §4.5.0): an inadmissible record must never reach here."
                )
                raise PreconditionError(message)

            if context.checkpoint.is_done(envelope.record_id):
                skipped += 1
                continue

            try:
                result = self.process_record(envelope, context)
            except Exception as exc:
                # A record failing is a value, not an abort: log it to the failure
                # queue and move on, so one bad record never kills its siblings or
                # the run (ARCHITECTURE.md §4.5.1, "failures are values").
                context.checkpoint.mark_failed(envelope.record_id, repr(exc))
                failed += 1
                continue

            context.store.append(self.name, result.outputs)
            context.checkpoint.mark_done(envelope.record_id)
            context.budget.record(result.cost)
            processed += 1
            emitted += len(result.outputs)

            if context.budget.exceeded and not context.budget.stop_at_stage_boundary:
                stopped_by_budget = True
                break

        if not stopped_by_budget:
            # Failures do not block completion: they go to the failure queue for a
            # separate retry pass (ARCHITECTURE.md §4.4, "a retry queue distinct
            # from the main output"), so a completed stage is not re-run wholesale.
            context.checkpoint.mark_stage_complete()

        return StageReport(
            stage=self.name,
            processed=processed,
            emitted=emitted,
            skipped=skipped,
            failed=failed,
            complete=not stopped_by_budget,
            stopped_by_budget=stopped_by_budget,
        )
