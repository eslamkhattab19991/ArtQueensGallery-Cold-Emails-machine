"""Tests for the inter-stage envelope.

The envelope is read by machinery that knows nothing about payloads — the
orchestrator, checkpoint manager, and run ledger. These tests cover the
guarantees that machinery relies on: lineage is complete, cost accumulates,
rejections are auditable, and a file from an incompatible build is refused
rather than silently misread.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from prospecting.domain.identifiers import RunId
from prospecting.schemas.envelope import (
    CURRENT_SCHEMA_VERSION,
    CostRecord,
    RecordStatus,
    StageEnvelope,
    StageName,
)
from prospecting.schemas.seed import OrganizationType, SeedOrganization

RUN = RunId("run_2026-07-23_001")


def make_seed(**overrides: object) -> SeedOrganization:
    values: dict[str, object] = {
        "row_number": 2,
        "name": "Maya Galerie Wien",
        "instagram": "@mayagalerie_wien",
        "website": "https://maya-galerie.at/",
        "organization_type": OrganizationType.GALLERY,
    }
    values.update(overrides)
    return SeedOrganization(**values)


def make_envelope(**overrides: object) -> StageEnvelope[SeedOrganization]:
    values: dict[str, object] = {
        "record_id": "seed_0002",
        "run_id": RUN,
        "stage": StageName.INPUT,
        # Deliberately well in the past: advance() stamps datetime.now(UTC), and a
        # fixture time later than "now" would make the freshness assertion
        # depend on the hour the suite runs.
        "created_at": datetime(2026, 1, 1, 12, tzinfo=UTC),
        "payload": make_seed(),
    }
    values.update(overrides)
    return StageEnvelope[SeedOrganization](**values)


class TestCostRecord:
    def test_defaults_to_zero(self) -> None:
        assert CostRecord().is_zero

    def test_any_nonzero_component_makes_it_nonzero(self) -> None:
        assert not CostRecord(crawls=1).is_zero

    def test_addition_sums_every_component(self) -> None:
        total = CostRecord(crawls=1, searches=2, llm_input_tokens=100, llm_calls=1).plus(
            CostRecord(crawls=3, dns_lookups=1, llm_input_tokens=50, llm_calls=2)
        )
        assert total.crawls == 4
        assert total.searches == 2
        assert total.dns_lookups == 1
        assert total.llm_input_tokens == 150
        assert total.llm_calls == 3

    def test_llm_calls_make_it_nonzero(self) -> None:
        assert not CostRecord(llm_calls=1).is_zero

    def test_addition_does_not_mutate_either_operand(self) -> None:
        """Costs accumulate across stages; an earlier stage's total is history."""
        first = CostRecord(crawls=1)
        second = CostRecord(crawls=2)
        first.plus(second)
        assert first.crawls == 1
        assert second.crawls == 2

    def test_rejects_negative_costs(self) -> None:
        with pytest.raises(ValidationError):
            CostRecord(crawls=-1)


class TestLineage:
    def test_starts_empty(self) -> None:
        assert make_envelope().lineage == ()

    def test_advancing_appends_the_previous_stage(self) -> None:
        advanced = make_envelope().advance(stage=StageName.DISCOVERY, payload=make_seed())
        assert advanced.lineage == (StageName.INPUT,)
        assert advanced.stage is StageName.DISCOVERY

    def test_lineage_accumulates_across_several_stages(self) -> None:
        envelope = make_envelope()
        for stage in (StageName.DISCOVERY, StageName.EXTRACTION, StageName.QUALIFICATION):
            envelope = envelope.advance(stage=stage, payload=make_seed())
        assert envelope.lineage == (
            StageName.INPUT,
            StageName.DISCOVERY,
            StageName.EXTRACTION,
        )

    def test_a_stage_cannot_appear_in_its_own_lineage(self) -> None:
        """Signals a re-run that overwrote a record, or lineage appended wrongly."""
        with pytest.raises(ValidationError, match="already appears in lineage"):
            make_envelope(stage=StageName.DISCOVERY, lineage=(StageName.DISCOVERY,))


class TestAdvance:
    def test_preserves_record_and_run_identity(self) -> None:
        """What makes a record traceable end to end."""
        original = make_envelope()
        advanced = original.advance(stage=StageName.DISCOVERY, payload=make_seed())
        assert advanced.record_id == original.record_id
        assert advanced.run_id == original.run_id

    def test_accumulates_cost(self) -> None:
        envelope = make_envelope(cost=CostRecord(crawls=1))
        advanced = envelope.advance(
            stage=StageName.DISCOVERY, payload=make_seed(), cost=CostRecord(crawls=2, searches=1)
        )
        assert advanced.cost.crawls == 3
        assert advanced.cost.searches == 1

    def test_carrying_no_cost_leaves_the_total_unchanged(self) -> None:
        envelope = make_envelope(cost=CostRecord(crawls=5))
        assert envelope.advance(stage=StageName.DISCOVERY, payload=make_seed()).cost.crawls == 5

    def test_does_not_mutate_the_original(self) -> None:
        original = make_envelope()
        original.advance(stage=StageName.DISCOVERY, payload=make_seed())
        assert original.stage is StageName.INPUT
        assert original.lineage == ()

    def test_stamps_a_fresh_timestamp(self) -> None:
        original = make_envelope()
        advanced = original.advance(stage=StageName.DISCOVERY, payload=make_seed())
        assert advanced.created_at > original.created_at


class TestRejection:
    def test_reject_sets_status_and_reason(self) -> None:
        rejected = make_envelope().reject("outside_priority_geography")
        assert rejected.status is RecordStatus.REJECTED
        assert rejected.reject_reason == "outside_priority_geography"

    def test_reject_preserves_the_payload(self) -> None:
        """rejected_candidates.csv must show what was rejected, not just that it was.

        A rejection you cannot inspect is a rubric you cannot tune.
        """
        rejected = make_envelope().reject("missing_full_name")
        assert rejected.payload.name == "Maya Galerie Wien"

    def test_rejection_without_a_reason_is_invalid(self) -> None:
        with pytest.raises(ValidationError, match="reject_reason is required"):
            make_envelope(status=RecordStatus.REJECTED)

    def test_active_records_need_no_reason(self) -> None:
        assert make_envelope().reject_reason is None


class TestTimestamp:
    def test_requires_timezone_awareness(self) -> None:
        """A resumed run may execute in a different zone."""
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_envelope(created_at=datetime(2026, 7, 23, 12))  # noqa: DTZ001

    def test_create_stamps_an_aware_timestamp(self) -> None:
        envelope = StageEnvelope.create(
            record_id="r", run_id=RUN, stage=StageName.INPUT, payload=make_seed()
        )
        assert envelope.created_at.tzinfo is not None


class TestSchemaVersionGuard:
    def test_current_version_is_readable(self) -> None:
        make_envelope().assert_readable()

    def test_a_different_major_version_is_refused(self) -> None:
        """Reading last month's JSONL must fail loudly, not coerce silently."""
        stale = make_envelope(schema_version="3.0")
        with pytest.raises(ValueError, match="schema version"):
            stale.assert_readable()

    def test_a_newer_minor_version_is_still_readable(self) -> None:
        """Minor bumps are additive; refusing them would block rolling upgrades."""
        minor = CURRENT_SCHEMA_VERSION.split(".")[0] + ".99"
        make_envelope(schema_version=minor).assert_readable()

    def test_the_error_names_both_versions_and_the_remedy(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            make_envelope(schema_version="1.0").assert_readable()
        message = str(exc_info.value)
        assert "1.0" in message
        assert CURRENT_SCHEMA_VERSION in message
        assert "migrate" in message.lower()


class TestWireFormat:
    def test_round_trips_through_json(self) -> None:
        """Stage files outlive the process that wrote them."""
        original = make_envelope(cost=CostRecord(crawls=2, searches=1))
        restored = StageEnvelope[SeedOrganization].model_validate_json(original.model_dump_json())
        assert restored == original

    def test_enums_serialize_as_wire_strings(self) -> None:
        payload = make_envelope().model_dump(mode="json")
        assert payload["stage"] == "input"
        assert payload["status"] == "active"

    def test_carries_every_documented_field(self) -> None:
        assert set(make_envelope().model_dump(mode="json")) == {
            "record_id",
            "run_id",
            "stage",
            "schema_version",
            "created_at",
            "lineage",
            "status",
            "reject_reason",
            "cost",
            "payload",
        }

    def test_is_immutable(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            make_envelope().status = RecordStatus.FAILED  # type: ignore[misc]
