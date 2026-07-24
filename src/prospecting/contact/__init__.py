"""Stage 5: the pluggable contact-discovery engine.

Sources are independent plugins scheduled in cost tiers and executed in parallel
within a tier; their results are then normalized, ownership-classified,
corroborated across sources, and ranked.

Adding a source (a browser agent, a new directory) is one new module plus one
config entry — the engine, the merge layer, and the pipeline stay untouched.

Dependency rule
---------------
Depends on ``prospecting.ports`` and ``prospecting.domain``, never on concrete
adapters. The registry additionally reads ``prospecting.config`` models — its
declared responsibility is to "enable sources from config" (ARCHITECTURE.md §7),
so it consumes the typed ``ContactSourcesConfig`` directly rather than having
settings threaded through as loose primitives.
"""
