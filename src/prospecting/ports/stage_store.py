"""The ``StageStore`` port: append and read the JSONL bus between stages.

ARCHITECTURE.md §3, §5: stages communicate only through files of
:class:`~prospecting.schemas.envelope.StageEnvelope` records. This port is the
seam through which the orchestrator and the checkpoint manager do that, without
knowing the payload type — the whole reason the envelope exists.

Why this port may import ``schemas`` while the others import only ``domain``.
A stage store's entire job is to move envelopes, and the envelope is a schema.
The Import Linter contract "Ports depend only on the domain" forbids ports from
reaching into the *application* layers (adapters, pipeline, contact, config, …);
it does not forbid the wire contracts in ``schemas``, which themselves depend on
nothing but the domain. So ``ports -> schemas -> domain`` is a straight line
inward, and this is the one port that needs it.

Synchronous by intent. Unlike the crawl/search/LLM/DNS ports, which the contact
engine fans out over concurrently, stage files are written and read by the
orchestrator one stage at a time. Making these methods ``async`` would impose
coroutine ceremony on a sequential consumer that gains no concurrency from it —
the opposite of the Interface Segregation the ports exist to provide.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol, TypeVar, runtime_checkable

from prospecting.domain.base import FrozenModel
from prospecting.schemas.envelope import StageEnvelope, StageName

__all__ = ["StageStore"]

#: The payload carried by the envelopes a given call reads or writes. Bound to
#: ``FrozenModel`` because every stage payload is a frozen domain/schema model.
PayloadT = TypeVar("PayloadT", bound=FrozenModel)


@runtime_checkable
class StageStore(Protocol):
    """Persist and retrieve the envelope stream for one run's stages."""

    def append(self, stage: StageName, records: Iterable[StageEnvelope[PayloadT]]) -> int:
        """Append ``records`` to ``stage``'s output and return how many were written.

        Append-only: a stage produces its file once and never rewrites it, which
        is what makes a partially completed stage resumable rather than corrupt.
        Every record's own ``stage`` must equal ``stage``; an implementation may
        reject a mismatch, since it signals a record written into the wrong file.
        """
        ...

    def read(
        self, stage: StageName, payload_type: type[PayloadT]
    ) -> Iterator[StageEnvelope[PayloadT]]:
        """Yield ``stage``'s records, each validated as carrying ``payload_type``.

        ``payload_type`` is required because the envelope is generic: the store
        cannot know from the file alone whether a payload is a ``SeedOrganization``
        or an ``ArtistProfile``, and guessing would defeat the type safety the
        envelope provides. Implementations call
        :meth:`~prospecting.schemas.envelope.StageEnvelope.assert_readable` on
        each record, so a file written by an incompatible schema version fails
        loudly here rather than surfacing later as corrupt data.
        """
        ...

    def has_stage(self, stage: StageName) -> bool:
        """Report whether ``stage`` has already produced output for this run.

        The primitive the checkpoint manager (Phase 7) resumes from: a stage
        whose output exists is not re-run. Kept separate from :meth:`read` so
        the check costs nothing when the answer is all that is needed.
        """
        ...
