"""The composition root: wire concrete adapters to ports and assemble a run.

ARCHITECTURE.md §7 — ``config/container``: "Wire adapters to ports from config",
and explicitly *not* contain business logic. This is the one module permitted to
import both the ports and their concrete adapters; every inward layer receives
its dependencies already constructed, which is what keeps vendor imports out of
the pipeline, the stages, and the contact engine.

It is deliberately thin and boring. Its job is assembly — "which implementation
backs which interface for this run" — expressed as plain functions rather than a
framework, so the wiring is readable top to bottom with no magic to trace.
"""

from __future__ import annotations

from prospecting.adapters.store.jsonl_stage_store import JsonlStageStore
from prospecting.config.models.settings import Settings
from prospecting.domain.identifiers import RunId
from prospecting.pipeline.base import Stage
from prospecting.ports.stage_store import StageStore

__all__ = ["build_pipeline_stages", "build_stage_store"]


def build_stage_store(settings: Settings, run_id: RunId) -> StageStore:
    """Construct the file-backed stage store for one run.

    The store writes under the run's interim directory, so two runs never read
    or overwrite each other's stage files.
    """
    return JsonlStageStore(directory=settings.paths.interim_for_run(run_id))


def build_pipeline_stages(settings: Settings) -> list[Stage]:
    """Assemble the ordered pipeline stages for a run.

    Empty until the concrete stages land with the providers: each stage is
    constructed here with the capability adapters it needs — a crawler, an LLM
    client, a DNS resolver — and none of those adapters exist yet. This is the
    wiring point, ready for them. A caller that receives an empty list should
    report that the pipeline is not yet runnable rather than hand an empty
    sequence to the orchestrator, which would reject it.
    """
    del settings  # will select and construct stages once the adapters exist
    return []
