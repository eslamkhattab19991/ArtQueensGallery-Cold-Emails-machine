"""Pure domain model: the vocabulary of the prospecting system.

Contains artist profiles, provenance, contact candidates, scores, and the
enumerations that give them meaning.

Dependency rule
---------------
This package imports **nothing** from ``prospecting`` and no infrastructure
library (no HTTP client, no SDK, no filesystem access). It is the one layer that
must survive every provider swap, storage change, and refactor. If a model here
imports a vendor SDK, the model has become coupled to that vendor.
"""
