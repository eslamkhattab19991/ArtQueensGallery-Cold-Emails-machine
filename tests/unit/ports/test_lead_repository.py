"""Tests for the ``LeadRepository`` port — the durable, cross-run artist store.

Unlike ``StageStore``, this port deals only in
:class:`~prospecting.domain.models.artist.ArtistProfile`, a pure domain model,
so the fake needs nothing from ``schemas``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from prospecting.domain.identifiers import CanonicalId
from prospecting.domain.models.artist import ArtistProfile
from prospecting.domain.provenance import Provenanced
from prospecting.ports.lead_repository import LeadRepository
from tests.support.factories import make_provenance


def make_artist(**overrides: object) -> ArtistProfile:
    values: dict[str, object] = {
        "canonical_id": CanonicalId("art_8f3a2b1c"),
        "full_name": Provenanced[str](value="Jane Doe", provenance=make_provenance()),
    }
    values.update(overrides)
    return ArtistProfile(**values)


class _FakeLeadRepository:
    """An in-memory ``LeadRepository`` — proves the port is satisfiable by shape."""

    def __init__(self) -> None:
        self._store: dict[CanonicalId, ArtistProfile] = {}

    def exists(self, canonical_id: CanonicalId) -> bool:
        return canonical_id in self._store

    def get(self, canonical_id: CanonicalId) -> ArtistProfile | None:
        return self._store.get(canonical_id)

    def upsert(self, profiles: Iterable[ArtistProfile]) -> int:
        count = 0
        for profile in profiles:
            self._store[profile.canonical_id] = profile
            count += 1
        return count

    def iter_all(self) -> Iterator[ArtistProfile]:
        yield from self._store.values()


class TestStructuralTyping:
    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeLeadRepository(), LeadRepository)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), LeadRepository)


class TestExistsAndGet:
    def test_exists_is_false_for_an_unknown_id(self) -> None:
        assert not _FakeLeadRepository().exists(CanonicalId("art_unknown"))

    def test_get_returns_none_for_an_unknown_id(self) -> None:
        assert _FakeLeadRepository().get(CanonicalId("art_unknown")) is None

    def test_exists_and_get_agree_after_an_upsert(self) -> None:
        repo = _FakeLeadRepository()
        artist = make_artist()
        repo.upsert([artist])
        assert repo.exists(artist.canonical_id)
        assert repo.get(artist.canonical_id) == artist


class TestUpsertUpdatesInPlace:
    """Identity resolution has already decided two records are the same artist.

    A returning artist must replace its prior snapshot, never create a second
    row — that would double-count a lead the pipeline already knows about.
    """

    def test_upsert_reports_the_count_applied(self) -> None:
        repo = _FakeLeadRepository()
        applied = repo.upsert([make_artist(), make_artist(canonical_id=CanonicalId("art_2"))])
        assert applied == 2

    def test_a_second_upsert_for_the_same_id_replaces_rather_than_duplicates(self) -> None:
        repo = _FakeLeadRepository()
        artist_id = CanonicalId("art_8f3a2b1c")
        repo.upsert([make_artist(canonical_id=artist_id)])
        repo.upsert(
            [
                make_artist(
                    canonical_id=artist_id,
                    full_name=Provenanced[str](value="Jane A. Doe", provenance=make_provenance()),
                )
            ]
        )
        assert len(list(repo.iter_all())) == 1
        assert repo.get(artist_id).full_name.value == "Jane A. Doe"  # type: ignore[union-attr]


class TestIterAll:
    def test_empty_repository_yields_nothing(self) -> None:
        assert list(_FakeLeadRepository().iter_all()) == []

    def test_yields_every_stored_artist(self) -> None:
        repo = _FakeLeadRepository()
        repo.upsert([make_artist(), make_artist(canonical_id=CanonicalId("art_2"))])
        assert len(list(repo.iter_all())) == 2
