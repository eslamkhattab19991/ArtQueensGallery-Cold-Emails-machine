"""Shared, importable test factories.

Plain functions rather than pytest fixtures: the objects built here (a valid
``Provenance``, an ``EmailCandidate``) are needed as *inputs* deep inside many
unrelated test modules, not as dependencies injected into a test's own
signature. A fixture would force every caller through pytest's dependency
injection for what is really just a constructor with sensible defaults.
"""
