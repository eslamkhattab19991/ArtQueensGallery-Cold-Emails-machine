"""Record-level checkpointing so a crashed stage resumes instead of restarting.

ARCHITECTURE.md Design Principle #3: "Every stage is resumable and idempotent. A
crash at stage 6 never re-pays for stages 1-5." This module is how a stage keeps
that promise *within* itself — a stage part-way through ten thousand artists must
not, on resume, re-pay for the ones it already finished. At real API prices that
difference is money, which is why the flush cadence is configurable per the cost
per record (:class:`~prospecting.config.models.checkpoint.CheckpointConfig`).

The manager tracks two things and nothing else:

* **Completed record ids** — buffered in memory and flushed to a checkpoint file
  every N records. On resume the stage asks :meth:`CheckpointManager.is_done`
  for each input record and skips the ones already finished. A crash loses at
  most the un-flushed buffer (< N records), never a corrupt file: the checkpoint
  is written to a temporary sibling and atomically renamed into place.
* **Failed records** — appended durably to a separate failure log the moment
  they fail, so the audit trail survives a crash even between flushes. A failed
  record is *not* marked done, so it is retried on the next run; the log is the
  record of what failed and why, not a decision about what to do next. Retry
  policy belongs to the orchestrator.

Disabling checkpointing (``enabled: false``) turns every method into a no-op that
touches no disk: the stage code calls the manager uniformly, and a run with
checkpointing off simply reprocesses everything, which is the documented meaning
of the flag.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from pydantic import Field, model_validator

from prospecting.config.models.checkpoint import CheckpointConfig
from prospecting.domain.base import FrozenModel
from prospecting.schemas.envelope import StageName

__all__ = ["CHECKPOINT_VERSION", "CheckpointError", "CheckpointManager", "FailureRecord"]

#: On-disk format version for the checkpoint file. Bumped only on an incompatible
#: change to the file's shape; a mismatch is refused loudly (see
#: :meth:`CheckpointManager._load`) rather than silently misread — the same guard
#: the stage envelope applies to its own records.
CHECKPOINT_VERSION = "1"


class CheckpointError(Exception):
    """A checkpoint file could not be read or is incompatible with this build.

    Raised rather than swallowed because a checkpoint that cannot be trusted must
    stop the run: silently starting from scratch would re-pay for every completed
    record, and silently continuing could skip records that were never actually
    done.
    """


class FailureRecord(FrozenModel):
    """One record that failed during a stage, logged for audit and retry.

    Carries only what is needed to find and retry the record — its id — plus why
    it failed and when. The record's payload is not duplicated here: the input to
    the stage still holds it, addressed by the same id.
    """

    record_id: str = Field(min_length=1, description="Id of the record that failed.")
    reason: str = Field(min_length=1, description="Why it failed, for the audit trail.")
    stage: StageName = Field(description="The stage in which it failed.")
    failed_at: datetime = Field(description="When it failed. Timezone-aware.")

    @model_validator(mode="after")
    def _timestamp_must_be_timezone_aware(self) -> Self:
        """Reject naive timestamps, matching every other dated record in the system."""
        if self.failed_at.tzinfo is None:
            message = (
                f"failed_at must be timezone-aware, got {self.failed_at!r}. Use datetime.now(UTC)."
            )
            raise ValueError(message)
        return self


class CheckpointManager:
    """Durable, resumable record-level progress for one stage of one run.

    Construct one per stage. When checkpointing is enabled it reads any existing
    checkpoint (unless resume is turned off), lets the stage skip completed
    records, and periodically flushes progress; when disabled it is inert.
    """

    def __init__(
        self,
        *,
        stage: StageName,
        directory: Path,
        config: CheckpointConfig,
        resume: bool | None = None,
    ) -> None:
        """Prepare checkpointing for ``stage`` under ``directory``.

        Args:
            stage: The stage this manager tracks progress for.
            directory: The run's checkpoint directory
                (``PathsConfig.checkpoints_for_run(run_id)``). The manager
                namespaces its files under a per-stage subdirectory of it.
            config: Checkpoint settings — flush cadence, filenames, and whether
                checkpointing and failure-separation are enabled.
            resume: Override for ``config.resume_by_default``. ``None`` uses the
                configured default; ``False`` starts the stage fresh, discarding
                any existing checkpoint.

        Raises:
            CheckpointError: An existing checkpoint is unreadable, was written by
                an incompatible version, or belongs to a different stage.
        """
        self._stage = stage
        self._config = config
        self._enabled = config.enabled
        self._resume = config.resume_by_default if resume is None else resume

        self._completed: set[str] = set()
        self._stage_complete = False
        self._since_flush = 0
        self._failure_count = 0

        self._stage_dir = directory / stage.value
        self._checkpoint_file = self._stage_dir / config.checkpoint_filename
        self._failure_file = self._stage_dir / config.failure_filename

        if not self._enabled:
            return

        self._stage_dir.mkdir(parents=True, exist_ok=True)
        if self._resume:
            self._load()
        else:
            self._checkpoint_file.unlink(missing_ok=True)
            self._failure_file.unlink(missing_ok=True)

    @property
    def enabled(self) -> bool:
        """Whether this manager writes checkpoints at all."""
        return self._enabled

    @property
    def resuming(self) -> bool:
        """Whether this run resumed from an existing checkpoint's state."""
        return self._enabled and self._resume

    @property
    def completed_count(self) -> int:
        """How many records are recorded as done, buffered and flushed alike."""
        return len(self._completed)

    @property
    def failure_count(self) -> int:
        """How many records have been logged as failed."""
        return self._failure_count

    def is_done(self, record_id: str) -> bool:
        """Whether ``record_id`` has already been completed and may be skipped.

        Always ``False`` when checkpointing is disabled, so a non-resumable run
        reprocesses every record — the documented behaviour of ``enabled: false``.
        """
        return record_id in self._completed

    def is_stage_complete(self) -> bool:
        """Whether the whole stage finished on a previous run and can be skipped."""
        return self._stage_complete

    def mark_done(self, record_id: str) -> None:
        """Record ``record_id`` as completed, flushing if the buffer is full.

        A no-op when disabled, and idempotent: marking the same id twice neither
        double-counts nor forces an extra flush.
        """
        if not self._enabled or record_id in self._completed:
            return
        self._completed.add(record_id)
        self._since_flush += 1
        if self._since_flush >= self._config.flush_every_n_records:
            self.flush()

    def mark_failed(self, record_id: str, reason: str) -> None:
        """Log ``record_id`` as failed, durably and immediately.

        A no-op when checkpointing is disabled, or when failure separation is
        turned off (``record_failures_separately: false``) — in which case the
        record is simply left un-done and retried on the next run. The append is
        immediate rather than buffered so the audit trail survives a crash
        between flushes.
        """
        if not self._enabled or not self._config.record_failures_separately:
            return
        record = FailureRecord(
            record_id=record_id, reason=reason, stage=self._stage, failed_at=datetime.now(UTC)
        )
        with self._failure_file.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        self._failure_count += 1

    def mark_stage_complete(self) -> None:
        """Mark the whole stage finished and flush, so a resume skips it entirely."""
        if not self._enabled:
            return
        self._stage_complete = True
        self.flush()

    def flush(self) -> None:
        """Write the completed set durably. A no-op when disabled.

        The write is atomic: the checkpoint is rendered to a temporary sibling
        file and renamed over the real one, so a crash mid-write leaves the
        previous checkpoint intact rather than a truncated, unreadable file.
        """
        if not self._enabled:
            return
        payload = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "stage": self._stage.value,
            "complete": self._stage_complete,
            "completed_record_ids": sorted(self._completed),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._atomic_write(self._checkpoint_file, json.dumps(payload, indent=2))
        self._since_flush = 0

    def failures(self) -> tuple[FailureRecord, ...]:
        """Return the logged failures, for the orchestrator's retry queue.

        Reads the failure log rather than an in-memory buffer, so it reflects
        failures from earlier runs too when resuming.
        """
        if not self._enabled or not self._failure_file.is_file():
            return ()
        records = []
        for line in self._failure_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                records.append(FailureRecord.model_validate_json(stripped))
        return tuple(records)

    def __enter__(self) -> Self:
        """Enter a context that flushes buffered progress on exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Flush any buffered completions so a clean exit loses no progress."""
        self.flush()

    def _load(self) -> None:
        """Read an existing checkpoint into memory, refusing an incompatible one."""
        self._failure_count = self._count_failures()
        if not self._checkpoint_file.is_file():
            return
        try:
            data = json.loads(self._checkpoint_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            message = f"checkpoint at {self._checkpoint_file} could not be read: {exc}"
            raise CheckpointError(message) from exc

        version = data.get("checkpoint_version")
        if version != CHECKPOINT_VERSION:
            message = (
                f"checkpoint at {self._checkpoint_file} was written with version {version!r}, "
                f"but this build reads {CHECKPOINT_VERSION!r}. Migrate or delete it to resume."
            )
            raise CheckpointError(message)

        stage = data.get("stage")
        if stage != self._stage.value:
            message = (
                f"checkpoint at {self._checkpoint_file} is for stage {stage!r}, "
                f"but this manager tracks {self._stage.value!r}."
            )
            raise CheckpointError(message)

        self._completed = set(data.get("completed_record_ids", []))
        self._stage_complete = bool(data.get("complete", False))

    def _count_failures(self) -> int:
        """Count the failures already logged, so resumed runs report a running total."""
        if not self._failure_file.is_file():
            return 0
        return sum(
            1
            for line in self._failure_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """Write ``text`` to ``path`` atomically via a temporary sibling and rename."""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
