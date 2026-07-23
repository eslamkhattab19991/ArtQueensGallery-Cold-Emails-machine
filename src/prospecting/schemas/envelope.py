"""The envelope every record travels in, at every stage.

ARCHITECTURE.md §5. One shape wraps every payload, which is what lets the
orchestrator, the run ledger, the checkpoint manager, and the resume logic be
written once and stay stage-agnostic: they read the envelope and never need to
know what a `DiscoveryCandidate` is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, Self, TypeVar

from pydantic import Field, model_validator

from prospecting.domain.base import FrozenModel
from prospecting.domain.identifiers import RunId

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "CostRecord",
    "RecordStatus",
    "StageEnvelope",
    "StageName",
]

#: Bumped whenever a payload or the envelope changes shape incompatibly.
#: ARCHITECTURE.md §10 requires a migration step for a version bump; the guard
#: in :meth:`StageEnvelope.assert_readable` is what makes that requirement
#: enforceable rather than aspirational.
CURRENT_SCHEMA_VERSION = "4.0"


class StageName(StrEnum):
    """The pipeline stages, in execution order.

    Values match ARCHITECTURE.md §2's diagram. ``PERSONALIZATION`` is 6b in the
    prose — it runs between verification and export — but a wire value of
    ``"6b"`` invites parsing bugs, so the stage is named rather than numbered.
    """

    INPUT = "input"
    DISCOVERY = "discovery"
    EXTRACTION = "extraction"
    QUALIFICATION = "qualification"
    CONTACT_DISCOVERY = "contact_discovery"
    VERIFICATION = "verification"
    PERSONALIZATION = "personalization"
    EXPORT = "export"


class RecordStatus(StrEnum):
    """Whether a record is still moving through the pipeline.

    Distinct from the *business outcome* (ARCHITECTURE.md §0), which is assigned
    only at export. This is transport state: is there more work to do on this
    record, did it drop out, or did it fail in a way worth retrying?
    """

    ACTIVE = "active"
    REJECTED = "rejected"
    FAILED = "failed"


class CostRecord(FrozenModel):
    """What one record cost to produce, accumulated across stages.

    Tracked per record rather than only per run because the budget ceilings in
    ARCHITECTURE.md §9 are enforced mid-run: the orchestrator needs to know what
    has been spent so far, and a per-run total that is only computable at the end
    cannot stop a runaway stage.
    """

    llm_input_tokens: int = Field(default=0, ge=0)
    llm_output_tokens: int = Field(default=0, ge=0)
    crawls: int = Field(default=0, ge=0)
    searches: int = Field(default=0, ge=0)
    dns_lookups: int = Field(default=0, ge=0)

    def plus(self, other: CostRecord) -> CostRecord:
        """Return the sum of two cost records.

        Returns a new instance rather than mutating: costs accumulate as a
        record moves between stages, and stages must not be able to reach back
        and rewrite what an earlier stage already spent.
        """
        return CostRecord(
            llm_input_tokens=self.llm_input_tokens + other.llm_input_tokens,
            llm_output_tokens=self.llm_output_tokens + other.llm_output_tokens,
            crawls=self.crawls + other.crawls,
            searches=self.searches + other.searches,
            dns_lookups=self.dns_lookups + other.dns_lookups,
        )

    @property
    def is_zero(self) -> bool:
        """Whether this record consumed no billable resources."""
        return not any(
            (
                self.llm_input_tokens,
                self.llm_output_tokens,
                self.crawls,
                self.searches,
                self.dns_lookups,
            )
        )


PayloadT = TypeVar("PayloadT", bound=FrozenModel)


# UP046 asks for PEP 695 type parameters (`class StageEnvelope[PayloadT]`).
# Pydantic v2 requires the explicit `Generic` base to specialise a model at
# runtime: without it, `StageEnvelope[SeedOrganization].model_validate_json(...)`
# does not resolve the payload type and validation silently degrades.
class StageEnvelope(FrozenModel, Generic[PayloadT]):  # noqa: UP046
    """One record in transit, with everything the pipeline needs to route it.

    The payload is whatever the stage produced; every other field exists so that
    machinery which knows nothing about the payload can still do its job —
    resume from a checkpoint, attribute cost, reconstruct how a record reached
    its current state, or refuse to read a file written by an incompatible build.
    """

    record_id: str = Field(min_length=1, description="Stable id for this record within the run.")
    run_id: RunId = Field(description="Which pipeline execution produced this.")
    stage: StageName = Field(description="The stage that wrote this record.")
    schema_version: str = Field(
        default=CURRENT_SCHEMA_VERSION, description="Envelope and payload shape version."
    )
    created_at: datetime = Field(description="When this record was written. Timezone-aware.")
    lineage: tuple[StageName, ...] = Field(
        default=(), description="Stages this record passed through, in order, excluding `stage`."
    )
    status: RecordStatus = Field(default=RecordStatus.ACTIVE)
    reject_reason: str | None = Field(
        default=None, description="Why the record dropped out. Required when status is rejected."
    )
    cost: CostRecord = Field(default_factory=CostRecord)
    payload: PayloadT = Field(description="The stage-specific record.")

    @model_validator(mode="after")
    def _timestamp_must_be_timezone_aware(self) -> Self:
        """Reject naive timestamps.

        Same rule as :class:`~prospecting.domain.provenance.Provenance`, for the
        same reason: a resumed run may execute on a different machine in a
        different zone, and "which record is newer?" must stay answerable.
        """
        if self.created_at.tzinfo is None:
            message = (
                f"created_at must be timezone-aware, got {self.created_at!r}. "
                "Use datetime.now(UTC)."
            )
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _rejection_must_state_a_reason(self) -> Self:
        """A rejected record must say why.

        ARCHITECTURE.md §4.4 requires rejects to be auditable so the rubric can
        be tuned. A rejection with no reason is exactly the record nobody can
        learn from — and after the spike found systematic accent bias, silent
        rejections are the specific failure mode to guard against.
        """
        if self.status is RecordStatus.REJECTED and not self.reject_reason:
            message = "reject_reason is required when status is 'rejected'."
            raise ValueError(message)
        return self

    @model_validator(mode="after")
    def _stage_must_not_repeat_in_lineage(self) -> Self:
        """The writing stage must not already appear in its own lineage.

        A stage appearing twice means either a re-run wrote into the same record
        instead of a new one, or lineage was appended in the wrong order. Both
        corrupt the audit trail, and both are silent without this check.
        """
        if self.stage in self.lineage:
            message = (
                f"stage {self.stage.value!r} already appears in lineage "
                f"{[s.value for s in self.lineage]}. Lineage records prior stages only."
            )
            raise ValueError(message)
        return self

    @classmethod
    def create(
        cls,
        *,
        record_id: str,
        run_id: RunId,
        stage: StageName,
        payload: PayloadT,
        cost: CostRecord | None = None,
    ) -> StageEnvelope[PayloadT]:
        """Build a first-stage envelope, stamped now.

        For records entering the pipeline. Use :meth:`advance` for a record that
        already exists and is moving to the next stage.
        """
        return cls(
            record_id=record_id,
            run_id=run_id,
            stage=stage,
            created_at=datetime.now(UTC),
            payload=payload,
            cost=cost or CostRecord(),
        )

    def advance[NextT: FrozenModel](
        self,
        *,
        stage: StageName,
        payload: NextT,
        cost: CostRecord | None = None,
    ) -> StageEnvelope[NextT]:
        """Return a new envelope carrying this record into the next stage.

        Appends the current stage to lineage and accumulates cost, so neither
        can be lost by a stage that forgets to carry them forward. The payload
        type changes — that is the point of the generic parameter — while
        ``record_id`` and ``run_id`` stay fixed, which is what makes a record
        traceable end to end.
        """
        return StageEnvelope[NextT](
            record_id=self.record_id,
            run_id=self.run_id,
            stage=stage,
            schema_version=self.schema_version,
            created_at=datetime.now(UTC),
            lineage=(*self.lineage, self.stage),
            status=self.status,
            reject_reason=self.reject_reason,
            cost=self.cost.plus(cost) if cost else self.cost,
            payload=payload,
        )

    def reject(self, reason: str) -> StageEnvelope[PayloadT]:
        """Return a copy marked rejected, preserving the payload for audit.

        The payload is deliberately kept: ``rejected_candidates.csv`` needs the
        artist's details to answer "was this rejection correct?" — a bare id and
        a reason string cannot be reviewed.
        """
        return self.model_copy(update={"status": RecordStatus.REJECTED, "reject_reason": reason})

    def assert_readable(self) -> None:
        """Raise if this record was written by an incompatible schema version.

        Called when reading a stage file. Without it, a build reading last
        month's JSONL silently coerces or drops fields, and the corruption
        surfaces later as inexplicable data rather than as a version mismatch.

        Raises:
            ValueError: The record's major version differs from this build's.
        """
        written = self.schema_version.split(".", 1)[0]
        current = CURRENT_SCHEMA_VERSION.split(".", 1)[0]
        if written != current:
            message = (
                f"Record {self.record_id!r} was written with schema version "
                f"{self.schema_version}, but this build reads {CURRENT_SCHEMA_VERSION}. "
                "Re-run the stage, or migrate the file before reading it."
            )
            raise ValueError(message)
