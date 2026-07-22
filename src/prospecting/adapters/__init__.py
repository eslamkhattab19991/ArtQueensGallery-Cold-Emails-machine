"""Concrete implementations of the ports, one subpackage per capability.

Each adapter absorbs the quirks of a single external system — authentication,
pagination, rate limits, error shapes, retries — so those details never leak
into a caller conditional.

Dependency rule
---------------
Adapters depend on ``prospecting.ports`` and ``prospecting.domain``. They must
not import the pipeline, contact engine, enrichment, scoring, identity, or
compliance layers, and they must carry no business logic: an adapter that
decides whether a lead is qualified is misplaced code.
"""
