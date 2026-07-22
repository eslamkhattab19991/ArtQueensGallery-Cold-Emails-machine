"""Abstract capability contracts implemented by adapters.

One narrow interface per capability — ``Crawler``, ``SearchProvider``,
``LLMClient``, ``DnsResolver``, ``ContactSource``, and the storage ports — so
that a consumer depends only on the operations it actually calls.

Dependency rule
---------------
Ports may import ``prospecting.domain`` and nothing else from this package.
They declare capabilities; they never implement them and hold no logic.
"""
