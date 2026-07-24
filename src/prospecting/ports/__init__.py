"""Abstract capability contracts implemented by adapters.

One narrow interface per capability — ``Crawler``, ``SearchProvider``,
``LLMClient``, ``DnsResolver``, ``Cache``, ``ContactSource``, and the storage
ports — so that a consumer depends only on the operations it actually calls
(Interface Segregation, ARCHITECTURE.md §8).

Every port is a :class:`typing.Protocol`, not a base class to inherit. An
adapter satisfies a port by shape alone, so it needs no import of this package —
the strongest possible form of "adapters never call inward" (ARCHITECTURE.md §3).
The composition root in ``config/container`` wires concrete adapters to these
contracts; mypy verifies the fit structurally.

Sync vs async is chosen per port, not globally. The four I/O ports the contact
engine fans out over concurrently — ``Crawler``, ``SearchProvider``,
``LLMClient``, ``DnsResolver`` — plus ``Cache`` and ``ContactSource`` are
``async``. The two orchestrator-facing stores the pipeline drives sequentially —
``StageStore`` and ``LeadRepository`` — are synchronous, because async would add
coroutine ceremony with no concurrency to gain.

Dependency rule
---------------
Ports may import ``prospecting.domain`` and ``prospecting.schemas`` — the wire
contracts, which themselves depend only on the domain — and nothing else from
this package. ``StageStore`` is the port that needs ``schemas`` (it moves
:class:`~prospecting.schemas.envelope.StageEnvelope` records); the rest deal only
in domain models. Ports declare capabilities; they never implement them and hold
no logic. This is enforced by the "Ports depend only on the domain" Import Linter
contract, whose forbidden list is the application layers, not ``schemas``.
"""

from __future__ import annotations

from prospecting.ports.cache import Cache
from prospecting.ports.contact_source import (
    ContactSearchContext,
    ContactSource,
    ContactSourceResult,
    CostEstimate,
    SourceOutcome,
)
from prospecting.ports.crawler import Crawler, CrawlResult, CrawlStatus
from prospecting.ports.dns_resolver import DnsResolution, DnsResolver
from prospecting.ports.lead_repository import LeadRepository
from prospecting.ports.llm_client import LLMClient, LlmMessage, LlmRequest, LlmResponse, LlmRole
from prospecting.ports.search_provider import SearchHit, SearchProvider
from prospecting.ports.stage_store import StageStore

__all__ = [
    "Cache",
    "ContactSearchContext",
    "ContactSource",
    "ContactSourceResult",
    "CostEstimate",
    "CrawlResult",
    "CrawlStatus",
    "Crawler",
    "DnsResolution",
    "DnsResolver",
    "LLMClient",
    "LeadRepository",
    "LlmMessage",
    "LlmRequest",
    "LlmResponse",
    "LlmRole",
    "SearchHit",
    "SearchProvider",
    "SourceOutcome",
    "StageStore",
]
