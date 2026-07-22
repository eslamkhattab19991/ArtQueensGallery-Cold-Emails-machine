"""Typed, immutable configuration sections.

One module per concern, aggregated by :class:`prospecting.config.models.settings.Settings`.
Every model is frozen and rejects unknown keys, so a mistyped YAML key fails
loudly at load time instead of silently doing nothing.
"""
