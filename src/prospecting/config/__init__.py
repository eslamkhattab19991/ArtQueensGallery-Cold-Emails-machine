"""Typed configuration loading and the dependency-injection composition root.

This package is the one place permitted to know about both ports and concrete
adapters: it reads ``config/providers.yaml`` and wires implementations to
interfaces at startup. Every other layer receives its dependencies already
constructed, which is what keeps the inward layers free of vendor imports.
"""
