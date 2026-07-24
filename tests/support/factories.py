"""Factory functions for constructing valid domain objects in tests.

Every factory accepts keyword overrides and fills in a sensible, valid default
for everything else, so a test can construct exactly the object its scenario
needs by naming only the fields that matter to it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from prospecting.domain.enums import EmailOwnership, ExtractionMethod, SourceType
from prospecting.domain.models.contact import EmailCandidate, PhoneCandidate
from prospecting.domain.provenance import Provenance

__all__ = ["make_email_candidate", "make_phone_candidate", "make_provenance"]

#: A fixed instant, not "now" — provenance timestamps must be deterministic
#: for tests to be reproducible and diffable.
_FIXED_INSTANT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def make_provenance(**overrides: object) -> Provenance:
    """Build a valid :class:`Provenance`, overriding only what a test cares about."""
    values: dict[str, object] = {
        "source_url": "https://example-artist.com/about",
        "source_type": SourceType.ARTIST_WEBSITE,
        "extraction_method": ExtractionMethod.LLM_EXTRACTION,
        "extracted_by": "claude-opus-4-8",
        "extracted_at": _FIXED_INSTANT,
        "confidence": 0.9,
        "evidence": "Jane Doe is a painter based in London.",
    }
    values.update(overrides)
    return Provenance(**values)


def make_email_candidate(**overrides: object) -> EmailCandidate:
    """Build a valid :class:`EmailCandidate`, overriding only what a test cares about."""
    values: dict[str, object] = {
        "email": "jane@example-artist.com",
        "ownership": EmailOwnership.ARTIST_OWNED,
        "provenance": make_provenance(
            extraction_method=ExtractionMethod.MAILTO_HREF,
            evidence=None,
            source_url="https://example-artist.com/contact",
        ),
    }
    values.update(overrides)
    return EmailCandidate(**values)


def make_phone_candidate(**overrides: object) -> PhoneCandidate:
    """Build a valid :class:`PhoneCandidate`, overriding only what a test cares about."""
    values: dict[str, object] = {
        "number": "+44 20 7946 0958",
        "provenance": make_provenance(
            extraction_method=ExtractionMethod.REGEX_MATCH,
            evidence=None,
            source_url="https://example-artist.com/contact",
        ),
    }
    values.update(overrides)
    return PhoneCandidate(**values)
