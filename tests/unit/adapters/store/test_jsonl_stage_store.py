"""Tests for the file-backed JSONL stage store.

Two properties matter beyond round-tripping: the store is append-only (so an
interrupted stage stays resumable), and it refuses a file written by an
incompatible schema version rather than silently coercing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prospecting.adapters.store.jsonl_stage_store import JsonlStageStore
from prospecting.domain.identifiers import RunId
from prospecting.schemas.envelope import StageEnvelope, StageName
from prospecting.schemas.seed import SeedOrganization

RUN_ID = RunId("run_test")


def _envelope(record_id: str, name: str) -> StageEnvelope[SeedOrganization]:
    return StageEnvelope.create(
        record_id=record_id,
        run_id=RUN_ID,
        stage=StageName.INPUT,
        payload=SeedOrganization(row_number=2, name=name, website="https://example.com"),
    )


class TestRoundTrip:
    def test_appends_and_reads_back(self, tmp_path: Path) -> None:
        store = JsonlStageStore(directory=tmp_path)
        assert store.append(StageName.INPUT, [_envelope("r1", "Alpha")]) == 1
        records = list(store.read(StageName.INPUT, SeedOrganization))
        assert len(records) == 1
        assert records[0].payload.name == "Alpha"

    def test_append_is_additive(self, tmp_path: Path) -> None:
        store = JsonlStageStore(directory=tmp_path)
        store.append(StageName.INPUT, [_envelope("r1", "Alpha")])
        store.append(StageName.INPUT, [_envelope("r2", "Beta")])
        assert len(list(store.read(StageName.INPUT, SeedOrganization))) == 2

    def test_each_stage_gets_its_own_file(self, tmp_path: Path) -> None:
        store = JsonlStageStore(directory=tmp_path)
        store.append(StageName.INPUT, [_envelope("r1", "Alpha")])
        assert (tmp_path / "input.jsonl").is_file()
        assert not (tmp_path / "discovery.jsonl").exists()


class TestPresence:
    def test_has_stage_is_false_before_any_write(self, tmp_path: Path) -> None:
        assert not JsonlStageStore(directory=tmp_path).has_stage(StageName.INPUT)

    def test_has_stage_is_true_after_a_write(self, tmp_path: Path) -> None:
        store = JsonlStageStore(directory=tmp_path)
        store.append(StageName.INPUT, [_envelope("r1", "Alpha")])
        assert store.has_stage(StageName.INPUT)

    def test_reading_a_missing_stage_yields_nothing(self, tmp_path: Path) -> None:
        assert (
            list(JsonlStageStore(directory=tmp_path).read(StageName.INPUT, SeedOrganization)) == []
        )

    def test_blank_lines_are_skipped_on_read(self, tmp_path: Path) -> None:
        """A stray blank line (a partial last write) must not become an empty record."""
        line = _envelope("r1", "Alpha").model_dump_json()
        (tmp_path / "input.jsonl").write_text(f"{line}\n\n", encoding="utf-8")
        records = list(JsonlStageStore(directory=tmp_path).read(StageName.INPUT, SeedOrganization))
        assert len(records) == 1


class TestSchemaGuard:
    def test_an_incompatible_version_is_refused_on_read(self, tmp_path: Path) -> None:
        incompatible = _envelope("r1", "Alpha").model_copy(update={"schema_version": "99.0"})
        (tmp_path / "input.jsonl").write_text(
            incompatible.model_dump_json() + "\n", encoding="utf-8"
        )
        store = JsonlStageStore(directory=tmp_path)
        with pytest.raises(ValueError, match="schema version"):
            list(store.read(StageName.INPUT, SeedOrganization))
