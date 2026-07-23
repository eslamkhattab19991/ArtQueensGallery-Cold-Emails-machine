"""Pure domain model: the vocabulary of the prospecting system.

Contains the artist profile, provenance, contact candidates, and the
enumerations that give them meaning.

Dependency rule
---------------
This package imports **nothing** from ``prospecting`` and no infrastructure
library (no HTTP client, no SDK, no filesystem access). It is the one layer
that must survive every provider change, storage change, and refactor. If a
model here imports a vendor SDK, the model has become coupled to that vendor.
Enforced by ``tests/architecture/`` and the Import Linter contracts in
``pyproject.toml``, not by convention.

Every model in this package is immutable (see
:class:`~prospecting.domain.base.FrozenModel`): a record is a snapshot, and
"updating" one means constructing a new instance, never mutating in place.
"""

from prospecting.domain.base import FrozenModel
from prospecting.domain.enums import (
    CareerStage,
    ContactStatus,
    EmailOwnership,
    ExhibitionType,
    ExtractionMethod,
    RejectReason,
    SourceTier,
    SourceType,
    Tier,
)
from prospecting.domain.identifiers import CanonicalId, RunId
from prospecting.domain.models import (
    ArtistProfile,
    Award,
    EmailCandidate,
    Exhibition,
    ExhibitionStats,
    PersonalizationHook,
    PressMention,
    Representation,
    Residency,
)
from prospecting.domain.provenance import Provenance, Provenanced

__all__ = [
    "ArtistProfile",
    "Award",
    "CanonicalId",
    "CareerStage",
    "ContactStatus",
    "EmailCandidate",
    "EmailOwnership",
    "Exhibition",
    "ExhibitionStats",
    "ExhibitionType",
    "ExtractionMethod",
    "FrozenModel",
    "PersonalizationHook",
    "PressMention",
    "Provenance",
    "Provenanced",
    "RejectReason",
    "Representation",
    "Residency",
    "RunId",
    "SourceTier",
    "SourceType",
    "Tier",
]
