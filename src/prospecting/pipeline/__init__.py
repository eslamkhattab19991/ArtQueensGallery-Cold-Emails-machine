"""Stage sequencing, checkpointing, resume, and budget enforcement.

The orchestrator owns *when* stages run; each stage owns *what* it does. Stages
communicate only through JSONL files on disk, which is what makes every stage
independently runnable, resumable, and idempotent.

Dependency rule
---------------
The pipeline depends on ``prospecting.ports``, ``prospecting.domain``,
``prospecting.schemas`` (the ``StageEnvelope`` records it routes), and
``prospecting.config`` models (checkpoint cadence, budgets). It must never import
``prospecting.adapters``: concrete implementations are injected by the
composition root, which is what allows the whole pipeline to be tested with fakes
and zero network access.
"""
