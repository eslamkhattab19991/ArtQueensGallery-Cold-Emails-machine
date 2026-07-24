"""Logging and, later, the run ledger, cost tracking, and per-source metrics.

Records what happened without altering it. The logging system
(:mod:`prospecting.observability.logger`) is the live piece: one configuration
point turns :class:`~prospecting.config.models.log.LogConfig` into structured
text or JSON, and every module logs through ``logging.getLogger(__name__)``.

Still to come, alongside the concrete stages that produce their data: the run
ledger (records processed, skipped, failed, retried; elapsed time), cost
tracking (spend by provider), and per-source yield metrics — the last of which
is what makes the pluggable source set prunable, since an extensible plugin
system is only as useful as the ability to measure and retire plugins that do
not earn their cost.
"""
