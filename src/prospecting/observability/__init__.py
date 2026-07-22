"""Run ledger, cost tracking, and per-source yield metrics.

Records what happened without altering it: records processed, skipped, failed,
and retried; elapsed time; spend by provider; and yield per contact source.
The last of these is what makes the pluggable source set prunable — an
extensible plugin system is only as useful as the ability to measure and retire
plugins that do not earn their cost.
"""
