"""Tests for the configuration section models and their validation rules.

The type-level rules are pydantic's job. What is tested here is the *semantic*
rules — the ones that catch a plausible-looking edit that would quietly corrupt
a run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from prospecting.config.models.base import FrozenConfig
from prospecting.config.models.icp import IcpConfig, SignalWeights, TierThresholds
from prospecting.config.models.paths import PathsConfig
from prospecting.config.models.retry import RetryConfig
from prospecting.config.models.runtime import RuntimeConfig


def _weights(**overrides: float) -> SignalWeights:
    values: dict[str, float] = {
        "exhibition_history": 30.0,
        "career_stage_fit": 25.0,
        "professional_presence": 15.0,
        "gallery_representation": 15.0,
        "english_fluency": 10.0,
        "personalization_potential": 5.0,
    }
    values.update(overrides)
    return SignalWeights(**values)


class TestFrozenConfigBehaviour:
    def test_sections_are_immutable(self) -> None:
        """Configuration must not change mid-run."""
        thresholds = TierThresholds(tier_a=75.0, tier_b=55.0, tier_c=40.0)
        with pytest.raises(ValidationError):
            thresholds.tier_a = 80.0  # type: ignore[misc]

    def test_unknown_keys_are_rejected(self) -> None:
        """A silently ignored typo is the most expensive kind of config bug."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            TierThresholds(tier_a=75.0, tier_b=55.0, tier_c=40.0, tier_d=10.0)  # type: ignore[call-arg]

    def test_base_class_is_configured_frozen_and_strict(self) -> None:
        assert FrozenConfig.model_config["frozen"] is True
        assert FrozenConfig.model_config["extra"] == "forbid"


class TestSignalWeights:
    def test_accepts_weights_totalling_one_hundred(self) -> None:
        assert _weights().as_mapping()["exhibition_history"] == 30.0

    def test_rejects_weights_that_do_not_total_one_hundred(self) -> None:
        """Editing one weight without rebalancing silently rescales every score."""
        with pytest.raises(ValidationError, match="must sum to 100"):
            _weights(exhibition_history=40.0)

    def test_rejects_negative_weights(self) -> None:
        with pytest.raises(ValidationError):
            _weights(english_fluency=-10.0, exhibition_history=50.0)

    def test_tolerates_floating_point_representation_error(self) -> None:
        """Thirds sum to 99.99999999999999 in binary floating point, not 100."""
        third = 100.0 / 3.0
        SignalWeights(
            exhibition_history=third,
            career_stage_fit=third,
            professional_presence=third,
            gallery_representation=0.0,
            english_fluency=0.0,
            personalization_potential=0.0,
        )

    def test_as_mapping_exposes_every_signal(self) -> None:
        assert set(_weights().as_mapping()) == {
            "exhibition_history",
            "career_stage_fit",
            "professional_presence",
            "gallery_representation",
            "english_fluency",
            "personalization_potential",
        }


class TestTierThresholds:
    def test_accepts_strictly_descending_thresholds(self) -> None:
        thresholds = TierThresholds(tier_a=75.0, tier_b=55.0, tier_c=40.0)
        assert thresholds.tier_a > thresholds.tier_b > thresholds.tier_c

    @pytest.mark.parametrize(
        ("a", "b", "c"),
        [
            (75.0, 75.0, 40.0),  # A and B collide: nothing can be tier B
            (55.0, 75.0, 40.0),  # inverted
            (75.0, 40.0, 55.0),  # inverted at the bottom
        ],
    )
    def test_rejects_non_descending_thresholds(self, a: float, b: float, c: float) -> None:
        with pytest.raises(ValidationError, match="strictly descend"):
            TierThresholds(tier_a=a, tier_b=b, tier_c=c)

    def test_rejects_thresholds_outside_the_score_range(self) -> None:
        with pytest.raises(ValidationError):
            TierThresholds(tier_a=150.0, tier_b=55.0, tier_c=40.0)


class TestIcpConfig:
    def _icp(self, **overrides: object) -> IcpConfig:
        values: dict[str, object] = {
            "rubric_version": "icp-v1.0",
            "priority_countries": frozenset({"GB", "FR"}),
            "allow_other_high_income_countries": True,
            "min_gender_confidence": 0.85,
            "min_field_confidence": 0.6,
            "signal_weights": _weights(),
            "tier_thresholds": TierThresholds(tier_a=75.0, tier_b=55.0, tier_c=40.0),
        }
        values.update(overrides)
        return IcpConfig(**values)

    def test_accepts_iso_alpha2_codes(self) -> None:
        assert self._icp().is_priority_country("GB")

    def test_country_lookup_is_case_insensitive(self) -> None:
        """Extracted values are not reliably uppercase."""
        assert self._icp().is_priority_country("gb")

    def test_reports_untargeted_countries(self) -> None:
        assert not self._icp().is_priority_country("BR")

    @pytest.mark.parametrize("bad", ["United Kingdom", "gb", "GBR", "G", ""])
    def test_rejects_anything_that_is_not_an_alpha2_code(self, bad: str) -> None:
        """A country name would never match an extracted code, silently dropping a market."""
        with pytest.raises(ValidationError, match="ISO 3166-1 alpha-2"):
            self._icp(priority_countries=frozenset({bad}))

    def test_rejects_an_empty_country_list(self) -> None:
        with pytest.raises(ValidationError):
            self._icp(priority_countries=frozenset())

    def test_explains_the_yaml_boolean_trap(self) -> None:
        """Unquoted NO in YAML becomes False; the error must name that cause.

        The default message ("Input should be a valid string") gives no hint
        that the parser ate a country code.
        """
        with pytest.raises(ValidationError, match="parsed as a boolean by YAML"):
            self._icp(priority_countries=["GB", False])

    @pytest.mark.parametrize("bad", [-0.1, 1.1])
    def test_rejects_confidence_outside_zero_to_one(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            self._icp(min_gender_confidence=bad)

    def test_rejects_an_empty_rubric_version(self) -> None:
        """The version stamps every score; blank makes scores untraceable."""
        with pytest.raises(ValidationError):
            self._icp(rubric_version="")


class TestRetryConfig:
    def _retry(self, **overrides: object) -> RetryConfig:
        values: dict[str, object] = {
            "max_attempts": 3,
            "initial_delay_seconds": 1.0,
            "max_delay_seconds": 30.0,
            "backoff_multiplier": 2.0,
            "jitter": True,
            "retryable_status_codes": frozenset({429, 503}),
        }
        values.update(overrides)
        return RetryConfig(**values)

    def test_first_attempt_has_no_delay(self) -> None:
        assert self._retry().delay_for_attempt(1) == 0.0

    def test_delay_grows_geometrically(self) -> None:
        retry = self._retry()
        assert retry.delay_for_attempt(2) == 1.0
        assert retry.delay_for_attempt(3) == 2.0
        assert retry.delay_for_attempt(4) == 4.0

    def test_delay_is_clamped_to_the_ceiling(self) -> None:
        assert self._retry().delay_for_attempt(20) == 30.0

    def test_multiplier_of_one_gives_constant_delay(self) -> None:
        retry = self._retry(backoff_multiplier=1.0)
        assert retry.delay_for_attempt(2) == retry.delay_for_attempt(5) == 1.0

    def test_rejects_a_ceiling_below_the_initial_delay(self) -> None:
        """Such a policy silently clamps the first backoff, making the setting a lie."""
        with pytest.raises(ValidationError, match="below"):
            self._retry(initial_delay_seconds=10.0, max_delay_seconds=5.0)

    def test_rejects_zero_attempts(self) -> None:
        with pytest.raises(ValidationError):
            self._retry(max_attempts=0)

    def test_single_attempt_disables_retrying(self) -> None:
        assert self._retry(max_attempts=1).max_attempts == 1


class TestRuntimeConfig:
    def _runtime(self, **overrides: object) -> RuntimeConfig:
        values: dict[str, object] = {
            "max_concurrent_requests": 8,
            "max_concurrent_per_domain": 2,
            "request_timeout_seconds": 30.0,
            "default_requests_per_minute": 30.0,
            "per_domain_requests_per_minute": {"artfacts.net": 60.0},
            "respect_robots_txt": True,
            "user_agent": "TestAgent/1.0",
        }
        values.update(overrides)
        return RuntimeConfig(**values)

    def test_returns_the_override_for_a_known_domain(self) -> None:
        assert self._runtime().requests_per_minute_for("artfacts.net") == 60.0

    def test_falls_back_to_the_default_rate(self) -> None:
        assert self._runtime().requests_per_minute_for("small-artist-site.com") == 30.0

    def test_rejects_zero_concurrency(self) -> None:
        with pytest.raises(ValidationError):
            self._runtime(max_concurrent_requests=0)

    def test_rejects_an_empty_user_agent(self) -> None:
        """An unidentified crawler is impolite and more likely to be blocked."""
        with pytest.raises(ValidationError):
            self._runtime(user_agent="")


class TestPathsConfig:
    def _paths(self, root: Path) -> PathsConfig:
        return PathsConfig(
            project_root=root,
            config_dir=root / "config",
            prompts_dir=root / "config" / "prompts",
            raw_dir=root / "data" / "raw",
            interim_dir=root / "data" / "interim",
            master_dir=root / "data" / "master",
            exports_dir=root / "data" / "exports",
            checkpoint_dir=root / "data" / "interim" / "_checkpoints",
        )

    def test_rejects_relative_paths(self, tmp_path: Path) -> None:
        """A relative path silently depends on the working directory."""
        with pytest.raises(ValidationError, match="absolute"):
            PathsConfig(
                project_root=Path("relative"),
                config_dir=tmp_path,
                prompts_dir=tmp_path,
                raw_dir=tmp_path,
                interim_dir=tmp_path,
                master_dir=tmp_path,
                exports_dir=tmp_path,
                checkpoint_dir=tmp_path,
            )

    def test_derives_run_scoped_directories(self, tmp_path: Path) -> None:
        """A run id is a runtime value, so run directories are derived, not configured."""
        paths = self._paths(tmp_path)
        run_id = "run_2026-07-23_001"
        assert paths.raw_for_run(run_id) == tmp_path / "data" / "raw" / run_id
        assert paths.interim_for_run(run_id) == tmp_path / "data" / "interim" / run_id
        assert paths.exports_for_run(run_id) == tmp_path / "data" / "exports" / run_id
        assert (
            paths.checkpoints_for_run(run_id)
            == tmp_path / "data" / "interim" / "_checkpoints" / run_id
        )
