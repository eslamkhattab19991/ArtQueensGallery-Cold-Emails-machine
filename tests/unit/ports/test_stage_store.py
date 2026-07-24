"""Tests for the ``StageStore`` port.

This is the one port that imports ``prospecting.schemas`` rather than only the
domain (see ``ports/__init__.py`` and ``stage_store.py`` for why that is still
within the port boundary). The fake here is deliberately in-memory rather than
file-backed — file I/O belongs to the adapter (Phase 6's
``jsonl_stage_store``), not to this port-level test.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import cast

import pytest

from prospecting.domain.base import FrozenModel
from prospecting.domain.identifiers import RunId
from prospecting.ports.stage_store import StageStore
from prospecting.schemas.envelope import StageEnvelope, StageName
from prospecting.schemas.seed import OrganizationType, SeedOrganization

_RUN = RunId("run_2026-07-24_001")


def make_seed_envelope(**overrides: object) -> StageEnvelope[SeedOrganization]:
    payload = SeedOrganization(
        row_number=2,
        name="Galerie COA",
        website="https://galeriecoa.com",
        organization_type=OrganizationType.GALLERY,
    )
    values: dict[str, object] = {
        "record_id": "seed_0002",
        "run_id": _RUN,
        "stage": StageName.INPUT,
        "payload": payload,
    }
    values.update(overrides)
    return StageEnvelope.create(**values)  # type: ignore[arg-type]


class _FakeStageStore:
    """An in-memory ``StageStore`` — proves the port is satisfiable by shape.

    The methods are generic in the payload type, exactly like the port they
    satisfy: ``StageEnvelope`` is invariant in its payload, so a single fixed
    element type could not accept both a ``SeedOrganization`` envelope and an
    ``ArtistProfile`` one. Storage is held as ``object`` and narrowed back on
    read — the file-backed adapter (Phase 6) does the same thing through JSON.
    """

    def __init__(self) -> None:
        self._records: dict[StageName, list[object]] = {}

    def append[P: FrozenModel](self, stage: StageName, records: Iterable[StageEnvelope[P]]) -> int:
        batch = list(records)
        for record in batch:
            if record.stage is not stage:
                message = f"record.stage={record.stage!r} does not match target stage={stage!r}"
                raise ValueError(message)
        self._records.setdefault(stage, []).extend(batch)
        return len(batch)

    def read[P: FrozenModel](
        self, stage: StageName, payload_type: type[P]
    ) -> Iterator[StageEnvelope[P]]:
        del payload_type  # A real adapter uses it to validate JSON; the fake holds objects.
        for record in self._records.get(stage, []):
            yield cast("StageEnvelope[P]", record)

    def has_stage(self, stage: StageName) -> bool:
        return bool(self._records.get(stage))


class TestStructuralTyping:
    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeStageStore(), StageStore)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), StageStore)


class TestAppendAndRead:
    def test_append_reports_how_many_records_were_written(self) -> None:
        store = _FakeStageStore()
        written = store.append(StageName.INPUT, [make_seed_envelope()])
        assert written == 1

    def test_read_returns_what_was_appended(self) -> None:
        store = _FakeStageStore()
        store.append(StageName.INPUT, [make_seed_envelope(record_id="seed_0002")])
        records = list(store.read(StageName.INPUT, SeedOrganization))
        assert [r.record_id for r in records] == ["seed_0002"]

    def test_a_stage_with_no_records_reads_as_empty(self) -> None:
        store = _FakeStageStore()
        assert list(store.read(StageName.DISCOVERY, SeedOrganization)) == []

    def test_rejects_a_record_written_to_the_wrong_stage(self) -> None:
        """Guards against a record ending up in a file that does not match it."""
        store = _FakeStageStore()
        mismatched = make_seed_envelope(stage=StageName.DISCOVERY)
        with pytest.raises(ValueError, match="does not match target stage"):
            store.append(StageName.INPUT, [mismatched])


class TestHasStage:
    def test_false_before_anything_is_written(self) -> None:
        assert not _FakeStageStore().has_stage(StageName.INPUT)

    def test_true_once_a_stage_has_output(self) -> None:
        """The primitive the checkpoint manager (Phase 7) resumes from."""
        store = _FakeStageStore()
        store.append(StageName.INPUT, [make_seed_envelope()])
        assert store.has_stage(StageName.INPUT)

    def test_false_for_a_different_stage(self) -> None:
        store = _FakeStageStore()
        store.append(StageName.INPUT, [make_seed_envelope()])
        assert not store.has_stage(StageName.DISCOVERY)
