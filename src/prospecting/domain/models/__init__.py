"""Composed domain value objects, and the ArtistProfile that aggregates them.

ARCHITECTURE.md §3 names this responsibility a single ``domain/models.py``
file. It is split here into one small module per concept — exhibition,
representation, recognition, personalization, contact, and the artist
aggregate itself — in service of the "small files, small classes" requirement.
The package boundary and the public names are unchanged from what the
architecture specifies; only the file layout inside the package differs.
"""

from prospecting.domain.models.artist import ArtistProfile
from prospecting.domain.models.contact import EmailCandidate
from prospecting.domain.models.exhibition import Exhibition, ExhibitionStats
from prospecting.domain.models.personalization import PersonalizationHook
from prospecting.domain.models.recognition import Award, PressMention, Residency
from prospecting.domain.models.representation import Representation

__all__ = [
    "ArtistProfile",
    "Award",
    "EmailCandidate",
    "Exhibition",
    "ExhibitionStats",
    "PersonalizationHook",
    "PressMention",
    "Representation",
    "Residency",
]
