"""A file-backed :class:`StageStore`: one append-only JSONL file per stage.

ARCHITECTURE.md §3, §5: stages communicate through JSONL files on disk. This is
that store — the concrete adapter behind the ``StageStore`` port, writing one
``<stage>.jsonl`` per stage under a run's interim directory. It carries no
business logic: it serializes envelopes on the way out and validates them on the
way back, and nothing else. Swapping it for a database is one adapter change.

Append-only, by design and not by accident (Design Principle #3). A stage writes
its output once; it never rewrites the file. That is what makes a stage
interrupted mid-way resumable — the records already written are still there and
still valid — rather than a half-rewritten file that resume cannot trust. Reads
validate each record's schema version, so a file left over from an incompatible
build fails loudly here instead of surfacing later as corrupt data.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TypeVar

from prospecting.domain.base import FrozenModel
from prospecting.schemas.envelope import StageEnvelope, StageName

__all__ = ["JsonlStageStore"]

PayloadT = TypeVar("PayloadT", bound=FrozenModel)


class JsonlStageStore:
    """Persist and read stage envelopes as one JSONL file per stage under a run.

    Constructed with the run's interim directory
    (``PathsConfig.interim_for_run(run_id)``); the file for each stage is derived
    from the stage name, so one store instance serves a whole run.
    """

    def __init__(self, *, directory: Path) -> None:
        """Store stage files under ``directory`` (a single run's interim folder)."""
        self._directory = directory

    def _path(self, stage: StageName) -> Path:
        return self._directory / f"{stage.value}.jsonl"

    def append(self, stage: StageName, records: Iterable[StageEnvelope[PayloadT]]) -> int:
        """Append ``records`` to ``stage``'s file, creating it if needed.

        Returns the number written. The parent directory is created lazily on
        first write, so an unused run leaves no empty directories behind.
        """
        path = self._path(stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json())
                handle.write("\n")
                written += 1
        return written

    def read(
        self, stage: StageName, payload_type: type[PayloadT]
    ) -> Iterator[StageEnvelope[PayloadT]]:
        """Yield ``stage``'s records, each validated as carrying ``payload_type``.

        Each record's :meth:`~prospecting.schemas.envelope.StageEnvelope.assert_readable`
        is checked, so a file written by an incompatible schema version stops the
        read loudly rather than being silently coerced.
        """
        path = self._path(stage)
        if not path.is_file():
            return
        # Parametrizing a generic by a runtime type value is beyond the type
        # checker; the in-memory store needs the same move. Runtime is correct.
        envelope_type: type[StageEnvelope[PayloadT]] = StageEnvelope[payload_type]  # type: ignore[valid-type]
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                envelope = envelope_type.model_validate_json(stripped)
                envelope.assert_readable()
                yield envelope

    def has_stage(self, stage: StageName) -> bool:
        """Whether ``stage`` has produced an output file for this run."""
        return self._path(stage).is_file()
