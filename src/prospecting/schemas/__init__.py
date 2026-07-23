"""Wire-format contracts exchanged between pipeline stages.

ARCHITECTURE.md §5 specifies a JSONL bus: each stage reads the previous stage's
file and writes its own. Those files outlive the process that wrote them — a
resumed run, a retry, or next month's run reads records serialized by an earlier
build. That makes these shapes a **contract**, not an implementation detail, and
it is why they live in their own package rather than inside any one stage.

Dependency rule
---------------
Schemas may import ``prospecting.domain`` and nothing else from this package.
The domain describes what an artist *is*; schemas describe how a record *travels*
— run identifiers, lineage, cost accounting, schema version. Keeping the two
apart is what allows the transport envelope to change without touching the
model, and vice versa.
"""

from prospecting.schemas.envelope import (
    CostRecord,
    RecordStatus,
    StageEnvelope,
    StageName,
)
from prospecting.schemas.seed import OrganizationType, SeedOrganization

__all__ = [
    "CostRecord",
    "OrganizationType",
    "RecordStatus",
    "SeedOrganization",
    "StageEnvelope",
    "StageName",
]
