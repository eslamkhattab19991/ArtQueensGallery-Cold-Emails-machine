"""In-memory test doubles for the storage ports.

Round-trip through JSON exactly as the real file-backed adapters will, so a test
exercises the same serialization the pipeline depends on — a payload that cannot
survive ``model_dump_json`` / ``model_validate_json`` fails here, not in
production.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

from prospecting.domain.base import FrozenModel
from prospecting.schemas.envelope import StageEnvelope, StageName

__all__ = ["InMemoryStageStore"]

PayloadT = TypeVar("PayloadT", bound=FrozenModel)


class InMemoryStageStore:
    """A ``StageStore`` that keeps each stage's records as JSON lines in memory."""

    def __init__(self) -> None:
        """Start with no records for any stage."""
        self._stages: dict[StageName, list[str]] = {}

    def append(self, stage: StageName, records: Iterable[StageEnvelope[PayloadT]]) -> int:
        """Append ``records`` to ``stage`` and return how many were written."""
        lines = self._stages.setdefault(stage, [])
        before = len(lines)
        lines.extend(record.model_dump_json() for record in records)
        return len(lines) - before

    def read(
        self, stage: StageName, payload_type: type[PayloadT]
    ) -> Iterator[StageEnvelope[PayloadT]]:
        """Yield ``stage``'s records, each validated as carrying ``payload_type``."""
        # Parametrizing a generic by a TypeVar's runtime value is something the
        # type checker cannot express; the real file-backed adapter needs the same
        # move. The runtime behaviour is exactly right — StageEnvelope[SeedOrg] etc.
        envelope_type: type[StageEnvelope[PayloadT]] = StageEnvelope[payload_type]  # type: ignore[valid-type]
        for line in self._stages.get(stage, []):
            yield envelope_type.model_validate_json(line)

    def has_stage(self, stage: StageName) -> bool:
        """Whether ``stage`` has produced any output."""
        return stage in self._stages
