"""Structural enforcement of the provenance rule from ARCHITECTURE.md §6.

    "Every extracted, inferred, or computed value in the domain model is
    wrapped [...] Provenance is not a discipline you remember to follow — it's
    checked."

This module is that check, at the type level. It introspects the domain models
rather than exercising them, so adding an untraced field to ``ArtistProfile``
fails the suite immediately — even if no other test ever touches that field.

Without a test like this, §6 is an intention that decays the first time someone
adds ``nationality: str`` in a hurry.
"""

from __future__ import annotations

import types
import typing

import pytest

from prospecting.domain.models.artist import ArtistProfile
from prospecting.domain.models.contact import EmailCandidate
from prospecting.domain.models.exhibition import Exhibition
from prospecting.domain.models.personalization import PersonalizationHook
from prospecting.domain.models.recognition import Award, PressMention, Residency
from prospecting.domain.models.representation import Representation
from prospecting.domain.provenance import Provenance, Provenanced

#: Fields on ArtistProfile that legitimately carry no provenance, each with the
#: reason it is exempt. An allowlist rather than a blanket skip: adding a field
#: here is a deliberate, reviewable act, which is the point.
FIELDS_EXEMPT_FROM_PROVENANCE: dict[str, str] = {
    "canonical_id": "System-assigned identifier, not a claim about the artist.",
    "tier": "Scoring output; traced by the rubric_version stamped on the score record.",
    "contact_status": "State marker produced by the engine, not read from a page.",
    "source_urls": "The provenance trail itself, not a value derived from one.",
    "first_seen_run": "Pipeline bookkeeping.",
    "previously_known": "Pipeline bookkeeping.",
}

#: Value objects that carry one Provenance for the whole entry, because a single
#: page states the entry as a unit (one CV line describes one exhibition).
ENTRY_LEVEL_PROVENANCE_MODELS = [
    Exhibition,
    Representation,
    Award,
    Residency,
    PressMention,
    PersonalizationHook,
    EmailCandidate,
]


def _unwrap_optional(annotation: object) -> object:
    """Return the non-None member of ``X | None``, or the annotation unchanged."""
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        non_none = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def _carries_provenance(annotation: object) -> bool:
    """Whether a field annotation guarantees provenance travels with the value.

    Three shapes satisfy the rule:

    * ``Provenanced[T]`` — a traced scalar or composite.
    * A model with its own ``provenance`` field — an entry-level value object.
    * ``tuple[M, ...]`` where ``M`` is such a model — a collection of them.
    """
    inner = _unwrap_optional(annotation)

    if isinstance(inner, type) and issubclass(inner, Provenanced):
        return True

    if isinstance(inner, type) and "provenance" in getattr(inner, "model_fields", {}):
        return True

    if typing.get_origin(inner) is tuple:
        args = [arg for arg in typing.get_args(inner) if arg is not Ellipsis]
        return bool(args) and all(_carries_provenance(arg) for arg in args)

    return False


@pytest.mark.invariant
def test_every_artist_field_is_traced_or_explicitly_exempt() -> None:
    """No field may enter ArtistProfile without provenance or a documented exemption."""
    untraced = [
        name
        for name, field in ArtistProfile.model_fields.items()
        if name not in FIELDS_EXEMPT_FROM_PROVENANCE and not _carries_provenance(field.annotation)
    ]

    assert not untraced, (
        "These ArtistProfile fields carry no provenance:\n"
        + "\n".join(f"  - {name}" for name in untraced)
        + "\n\nWrap the value in Provenanced[T], or — if it is genuinely not a "
        "claim about the artist — add it to FIELDS_EXEMPT_FROM_PROVENANCE with "
        "the reason."
    )


@pytest.mark.invariant
def test_the_exemption_list_has_no_stale_entries() -> None:
    """An exemption for a field that no longer exists hides a real gap later.

    A stale name silently pre-authorises whatever field is added under it next.
    """
    stale = sorted(set(FIELDS_EXEMPT_FROM_PROVENANCE) - set(ArtistProfile.model_fields))
    assert not stale, f"Exemptions for fields that no longer exist: {stale}"


@pytest.mark.invariant
def test_every_exemption_states_a_reason() -> None:
    """The list is only reviewable if each entry explains itself."""
    unexplained = [
        name for name, reason in FIELDS_EXEMPT_FROM_PROVENANCE.items() if len(reason.strip()) < 20
    ]
    assert not unexplained, f"Exemptions lacking a real justification: {unexplained}"


@pytest.mark.invariant
@pytest.mark.parametrize("model", ENTRY_LEVEL_PROVENANCE_MODELS)
def test_entry_level_models_require_provenance(model: type) -> None:
    """Each value object carries a mandatory, non-optional Provenance."""
    field = model.model_fields.get("provenance")  # type: ignore[attr-defined]
    assert field is not None, f"{model.__name__} has no provenance field"
    assert field.is_required(), f"{model.__name__}.provenance must not be optional"
    assert field.annotation is Provenance, (
        f"{model.__name__}.provenance must be a Provenance, got {field.annotation}"
    )


@pytest.mark.invariant
def test_the_detector_rejects_an_untraced_field() -> None:
    """Prove the check can fail — a guard that detects nothing passes just as quietly.

    ``tests/architecture`` applies the same reasoning to the layering rules.
    """
    assert not _carries_provenance(str)
    assert not _carries_provenance(int | None)
    assert not _carries_provenance(tuple[str, ...])


@pytest.mark.invariant
def test_the_detector_accepts_each_valid_shape() -> None:
    """The mirror of the previous test: it must not reject what the model uses."""
    assert _carries_provenance(Provenanced[str])
    assert _carries_provenance(Provenanced[str] | None)
    assert _carries_provenance(Exhibition)
    assert _carries_provenance(tuple[Exhibition, ...])
