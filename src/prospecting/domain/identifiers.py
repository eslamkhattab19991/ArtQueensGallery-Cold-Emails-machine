"""Distinct identifier types for values that must never be interchanged.

Both are plain strings at runtime — pydantic validates and serializes them
exactly like ``str`` — but :func:`typing.NewType` gives mypy a nominal type it
can tell apart. A function that expects a ``CanonicalId`` will not silently
accept a ``RunId`` passed by mistake, even though both are strings under the
hood. This catches the specific class of bug where two ID-shaped strings get
swapped at a call site and nothing fails until the wrong artist is updated or
the wrong run's cache is read.
"""

from __future__ import annotations

from typing import NewType

__all__ = ["CanonicalId", "RunId"]

CanonicalId = NewType("CanonicalId", str)
"""Identifies one artist across every run, e.g. ``"art_8f3a2b1c"``.

Assigned once during identity resolution (ARCHITECTURE.md §4.3c) and stable for
the artist's lifetime in ``data/master/artists.jsonl``.
"""

RunId = NewType("RunId", str)
"""Identifies one pipeline execution, e.g. ``"run_2026-07-23_001"``.

Used to namespace a run's interim, raw-cache, and export directories — see
``PathsConfig.raw_for_run`` and its siblings in
:mod:`prospecting.config.models.paths`.
"""
