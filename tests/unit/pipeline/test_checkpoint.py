"""Tests for the record-level checkpoint manager.

The behaviours that matter are resumability (a second manager sees the first's
flushed progress), crash safety (an interrupted run loses at most the un-flushed
buffer and never a corrupt file), and the loud refusal of a checkpoint that
cannot be trusted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from prospecting.config.models.checkpoint import CheckpointConfig
from prospecting.pipeline.checkpoint import (
    CHECKPOINT_VERSION,
    CheckpointError,
    CheckpointManager,
    FailureRecord,
)
from prospecting.schemas.envelope import StageName

STAGE = StageName.DISCOVERY


def make_config(**overrides: object) -> CheckpointConfig:
    values: dict[str, object] = {
        "enabled": True,
        "flush_every_n_records": 3,
        "resume_by_default": True,
        "record_failures_separately": True,
        "checkpoint_filename": "checkpoint.json",
        "failure_filename": "failures.jsonl",
    }
    values.update(overrides)
    return CheckpointConfig(**values)


def make_manager(directory: Path, **overrides: object) -> CheckpointManager:
    return CheckpointManager(stage=STAGE, directory=directory, config=make_config(**overrides))


class TestCompletionTracking:
    def test_a_marked_record_is_done(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path)
        manager.mark_done("rec-1")
        assert manager.is_done("rec-1")

    def test_an_unmarked_record_is_not_done(self, tmp_path: Path) -> None:
        assert not make_manager(tmp_path).is_done("rec-1")

    def test_marking_twice_does_not_double_count(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path)
        manager.mark_done("rec-1")
        manager.mark_done("rec-1")
        assert manager.completed_count == 1


class TestFlushCadence:
    def test_reaching_the_threshold_flushes_automatically(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path, flush_every_n_records=3)
        for index in range(3):
            manager.mark_done(f"rec-{index}")
        # A fresh manager sees the flushed records, proving they hit disk.
        resumed = make_manager(tmp_path)
        assert {resumed.is_done(f"rec-{index}") for index in range(3)} == {True}

    def test_the_unflushed_buffer_is_lost_on_a_crash(self, tmp_path: Path) -> None:
        """At most flush_every_n_records-1 records are repeated — the durability trade."""
        manager = make_manager(tmp_path, flush_every_n_records=5)
        manager.mark_done("rec-a")
        manager.mark_done("rec-b")
        # No flush, no close: simulate a crash by abandoning `manager`.
        resumed = make_manager(tmp_path)
        assert not resumed.is_done("rec-a")
        assert not resumed.is_done("rec-b")

    def test_explicit_flush_persists_a_partial_buffer(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path, flush_every_n_records=100)
        manager.mark_done("rec-a")
        manager.flush()
        assert make_manager(tmp_path).is_done("rec-a")

    def test_the_checkpoint_file_is_valid_and_sorted(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path, flush_every_n_records=100)
        for record_id in ("rec-c", "rec-a", "rec-b"):
            manager.mark_done(record_id)
        manager.flush()
        data = json.loads((tmp_path / "discovery" / "checkpoint.json").read_text(encoding="utf-8"))
        assert data["checkpoint_version"] == CHECKPOINT_VERSION
        assert data["stage"] == "discovery"
        assert data["completed_record_ids"] == ["rec-a", "rec-b", "rec-c"]


class TestResume:
    def test_a_new_manager_resumes_flushed_progress(self, tmp_path: Path) -> None:
        with make_manager(tmp_path) as manager:
            manager.mark_done("rec-1")
        assert make_manager(tmp_path).is_done("rec-1")

    def test_context_manager_flushes_on_exit(self, tmp_path: Path) -> None:
        with make_manager(tmp_path, flush_every_n_records=100) as manager:
            manager.mark_done("rec-1")
        # Exit flushed despite never reaching the threshold.
        assert make_manager(tmp_path).is_done("rec-1")

    def test_resume_disabled_starts_fresh_and_clears_the_file(self, tmp_path: Path) -> None:
        with make_manager(tmp_path, flush_every_n_records=1) as first:
            first.mark_done("rec-1")
        restarted = CheckpointManager(
            stage=STAGE, directory=tmp_path, config=make_config(), resume=False
        )
        assert not restarted.is_done("rec-1")
        assert not (tmp_path / "discovery" / "checkpoint.json").is_file()


class TestStageCompletion:
    def test_marking_the_stage_complete_persists(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path)
        manager.mark_stage_complete()
        assert make_manager(tmp_path).is_stage_complete()

    def test_a_stage_is_not_complete_until_marked(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path)
        manager.mark_done("rec-1")
        manager.flush()
        assert not make_manager(tmp_path).is_stage_complete()


class TestFailures:
    def test_a_failure_is_logged_immediately(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path)
        manager.mark_failed("rec-1", "network timeout")
        # Durable at once, without a flush: a fresh manager counts it.
        assert make_manager(tmp_path).failure_count == 1

    def test_failures_can_be_read_back(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path)
        manager.mark_failed("rec-1", "network timeout")
        failures = manager.failures()
        assert len(failures) == 1
        assert failures[0].record_id == "rec-1"
        assert failures[0].reason == "network timeout"
        assert failures[0].stage is StageName.DISCOVERY

    def test_a_failed_record_is_not_marked_done(self, tmp_path: Path) -> None:
        """It must be retried on resume, not skipped."""
        manager = make_manager(tmp_path)
        manager.mark_failed("rec-1", "boom")
        assert not manager.is_done("rec-1")

    def test_failure_separation_can_be_turned_off(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path, record_failures_separately=False)
        manager.mark_failed("rec-1", "boom")
        assert manager.failure_count == 0
        assert not (tmp_path / "discovery" / "failures.jsonl").is_file()


class TestIntrospection:
    def test_enabled_reflects_config(self, tmp_path: Path) -> None:
        assert make_manager(tmp_path).enabled
        assert not make_manager(tmp_path, enabled=False).enabled

    def test_resuming_is_true_when_enabled_and_resuming(self, tmp_path: Path) -> None:
        assert make_manager(tmp_path).resuming

    def test_resuming_is_false_when_disabled(self, tmp_path: Path) -> None:
        assert not make_manager(tmp_path, enabled=False).resuming

    def test_failures_is_empty_when_none_are_logged(self, tmp_path: Path) -> None:
        assert make_manager(tmp_path).failures() == ()


class TestDisabled:
    def test_nothing_is_recorded_when_disabled(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path, enabled=False)
        manager.mark_done("rec-1")
        assert not manager.is_done("rec-1")

    def test_no_files_are_written_when_disabled(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path, enabled=False)
        manager.mark_done("rec-1")
        manager.mark_failed("rec-1", "boom")
        manager.flush()
        assert not (tmp_path / "discovery").exists()

    def test_stage_completion_is_a_no_op_when_disabled(self, tmp_path: Path) -> None:
        manager = make_manager(tmp_path, enabled=False)
        manager.mark_stage_complete()
        assert not manager.is_stage_complete()


class TestCorruptOrIncompatibleCheckpoints:
    def _write_checkpoint(self, tmp_path: Path, text: str) -> None:
        stage_dir = tmp_path / "discovery"
        stage_dir.mkdir(parents=True)
        (stage_dir / "checkpoint.json").write_text(text, encoding="utf-8")

    def test_an_incompatible_version_is_refused(self, tmp_path: Path) -> None:
        self._write_checkpoint(
            tmp_path,
            json.dumps(
                {"checkpoint_version": "999", "stage": "discovery", "completed_record_ids": []}
            ),
        )
        with pytest.raises(CheckpointError, match="version"):
            make_manager(tmp_path)

    def test_a_checkpoint_for_another_stage_is_refused(self, tmp_path: Path) -> None:
        self._write_checkpoint(
            tmp_path,
            json.dumps(
                {
                    "checkpoint_version": CHECKPOINT_VERSION,
                    "stage": "export",
                    "completed_record_ids": [],
                }
            ),
        )
        with pytest.raises(CheckpointError, match="stage"):
            make_manager(tmp_path)

    def test_unreadable_json_is_refused(self, tmp_path: Path) -> None:
        self._write_checkpoint(tmp_path, "{ this is not valid json")
        with pytest.raises(CheckpointError, match="could not be read"):
            make_manager(tmp_path)


class TestFailureRecord:
    def test_rejects_a_naive_timestamp(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            FailureRecord(
                record_id="rec-1",
                reason="boom",
                stage=StageName.DISCOVERY,
                failed_at=datetime(2026, 1, 1, 12, 0),  # noqa: DTZ001 - deliberately naive
            )

    def test_accepts_a_timezone_aware_timestamp(self) -> None:
        record = FailureRecord(
            record_id="rec-1",
            reason="boom",
            stage=StageName.DISCOVERY,
            failed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        assert record.failed_at.tzinfo is UTC
