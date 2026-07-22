"""Deterministic filters, the weighted qualification rubric, and confidence models.

Hard filters are pure functions over the domain model and never call an LLM.
Rubric weights are loaded from configuration, never hard-coded, so retuning the
ideal-artist profile is a config change rather than a code change.
"""
