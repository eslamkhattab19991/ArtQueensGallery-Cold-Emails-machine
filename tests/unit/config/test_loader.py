"""Tests for configuration loading, layering, and precedence.

Every test drives the loader with an injected configuration directory and an
injected environment mapping, so nothing here depends on the developer's real
environment or mutates process state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from prospecting.config.errors import (
    ConfigFileNotFoundError,
    ConfigValidationError,
)
from prospecting.config.loader import CONFIG_FILES, load_settings, resolve_project_root

MINIMAL_RUNTIME = """
paths:
  prompts_dir: config/prompts
  raw_dir: data/raw
  interim_dir: data/interim
  master_dir: data/master
  exports_dir: data/exports
  checkpoint_dir: data/interim/_checkpoints
runtime:
  max_concurrent_requests: 8
  max_concurrent_per_domain: 2
  request_timeout_seconds: 30.0
  default_requests_per_minute: 30.0
  per_domain_requests_per_minute: {}
  respect_robots_txt: true
  user_agent: "TestAgent/1.0"
retry:
  max_attempts: 3
  initial_delay_seconds: 1.0
  max_delay_seconds: 30.0
  backoff_multiplier: 2.0
  jitter: true
  retryable_status_codes: [429, 503]
checkpoint:
  enabled: true
  flush_every_n_records: 25
  resume_by_default: true
  record_failures_separately: true
  checkpoint_filename: checkpoint.json
  failure_filename: failures.jsonl
log:
  level: INFO
  format: text
  progress_every_n_records: 25
  include_timestamps: true
  log_cost_estimates: true
budget:
  enabled: true
  max_usd_per_run: 25.0
  max_crawls_per_run: 2000
  max_searches_per_run: 500
  max_llm_calls_per_run: 1000
  stop_at_stage_boundary: true
"""

MINIMAL_ICP = """
icp:
  rubric_version: icp-test
  priority_countries: [GB, FR]
  allow_other_high_income_countries: true
  min_gender_confidence: 0.85
  min_field_confidence: 0.6
  signal_weights:
    exhibition_history: 30.0
    career_stage_fit: 25.0
    professional_presence: 15.0
    gallery_representation: 15.0
    english_fluency: 10.0
    personalization_potential: 5.0
  tier_thresholds:
    tier_a: 75.0
    tier_b: 55.0
    tier_c: 40.0
"""


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A complete, valid configuration directory isolated per test."""
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "runtime.yaml").write_text(MINIMAL_RUNTIME, encoding="utf-8")
    (directory / "icp.yaml").write_text(MINIMAL_ICP, encoding="utf-8")
    (directory / "profiles").mkdir()
    return directory


class TestBaselineLoad:
    def test_loads_every_section(self, config_dir: Path, tmp_path: Path) -> None:
        settings = load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)
        assert settings.runtime.max_concurrent_requests == 8
        assert settings.icp.rubric_version == "icp-test"
        assert settings.budget.enabled is True

    def test_result_is_immutable(self, config_dir: Path, tmp_path: Path) -> None:
        settings = load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)
        with pytest.raises(ValidationError, match="frozen"):
            settings.runtime.max_concurrent_requests = 99  # type: ignore[misc]

    def test_records_the_files_it_merged(self, config_dir: Path, tmp_path: Path) -> None:
        """Provenance: "why is this value what it is?" must be answerable."""
        settings = load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)
        assert settings.meta.files_loaded == (
            config_dir / "runtime.yaml",
            config_dir / "icp.yaml",
        )
        assert settings.meta.profile is None
        assert settings.meta.environment_overrides == ()

    def test_missing_section_file_names_the_file(self, tmp_path: Path) -> None:
        directory = tmp_path / "config"
        directory.mkdir()
        (directory / "runtime.yaml").write_text(MINIMAL_RUNTIME, encoding="utf-8")
        with pytest.raises(ConfigFileNotFoundError, match=r"icp\.yaml"):
            load_settings(config_dir=directory, environ={}, project_root=tmp_path)


class TestPathResolution:
    def test_relative_paths_resolve_against_the_project_root(
        self, config_dir: Path, tmp_path: Path
    ) -> None:
        settings = load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)
        assert settings.paths.raw_dir == tmp_path / "data" / "raw"
        assert settings.paths.raw_dir.is_absolute()

    def test_absolute_paths_are_left_alone(self, config_dir: Path, tmp_path: Path) -> None:
        elsewhere = tmp_path / "elsewhere" / "raw"
        (config_dir / "runtime.yaml").write_text(
            MINIMAL_RUNTIME.replace("raw_dir: data/raw", f"raw_dir: {elsewhere.as_posix()}"),
            encoding="utf-8",
        )
        settings = load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)
        assert settings.paths.raw_dir == elsewhere

    def test_project_root_and_config_dir_are_injected_not_configured(
        self, config_dir: Path, tmp_path: Path
    ) -> None:
        """Both are facts about where the process runs; a file must not override them."""
        settings = load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)
        assert settings.paths.project_root == tmp_path
        assert settings.paths.config_dir == config_dir


class TestProfileOverlay:
    def test_overlay_changes_only_what_it_restates(self, config_dir: Path, tmp_path: Path) -> None:
        (config_dir / "profiles" / "dev.yaml").write_text(
            "runtime:\n  max_concurrent_requests: 2\n", encoding="utf-8"
        )
        settings = load_settings(
            config_dir=config_dir, profile="dev", environ={}, project_root=tmp_path
        )
        assert settings.runtime.max_concurrent_requests == 2
        assert settings.runtime.max_concurrent_per_domain == 2  # untouched by the overlay
        assert settings.meta.profile == "dev"

    def test_profile_can_come_from_the_environment(self, config_dir: Path, tmp_path: Path) -> None:
        (config_dir / "profiles" / "dev.yaml").write_text(
            "log:\n  level: DEBUG\n", encoding="utf-8"
        )
        settings = load_settings(
            config_dir=config_dir,
            environ={"PROSPECTING_PROFILE": "dev"},
            project_root=tmp_path,
        )
        assert settings.log.level == "DEBUG"
        assert settings.meta.profile == "dev"

    def test_explicit_argument_beats_the_environment(
        self, config_dir: Path, tmp_path: Path
    ) -> None:
        (config_dir / "profiles" / "dev.yaml").write_text(
            "log:\n  level: DEBUG\n", encoding="utf-8"
        )
        (config_dir / "profiles" / "test.yaml").write_text(
            "log:\n  level: ERROR\n", encoding="utf-8"
        )
        settings = load_settings(
            config_dir=config_dir,
            profile="test",
            environ={"PROSPECTING_PROFILE": "dev"},
            project_root=tmp_path,
        )
        assert settings.log.level == "ERROR"

    def test_a_misspelled_profile_is_an_error_not_a_silent_fallback(
        self, config_dir: Path, tmp_path: Path
    ) -> None:
        """Falling back to baseline would run production settings under a dev name."""
        with pytest.raises(ConfigFileNotFoundError, match="typo-profile"):
            load_settings(
                config_dir=config_dir,
                profile="typo-profile",
                environ={},
                project_root=tmp_path,
            )


class TestEnvironmentOverrides:
    def test_override_beats_the_baseline(self, config_dir: Path, tmp_path: Path) -> None:
        settings = load_settings(
            config_dir=config_dir,
            environ={"PROSPECTING__RUNTIME__MAX_CONCURRENT_REQUESTS": "3"},
            project_root=tmp_path,
        )
        assert settings.runtime.max_concurrent_requests == 3

    def test_override_beats_the_profile(self, config_dir: Path, tmp_path: Path) -> None:
        """Highest precedence: the operator on this machine has the last word."""
        (config_dir / "profiles" / "dev.yaml").write_text(
            "runtime:\n  max_concurrent_requests: 2\n", encoding="utf-8"
        )
        settings = load_settings(
            config_dir=config_dir,
            profile="dev",
            environ={"PROSPECTING__RUNTIME__MAX_CONCURRENT_REQUESTS": "5"},
            project_root=tmp_path,
        )
        assert settings.runtime.max_concurrent_requests == 5

    def test_overrides_are_recorded_in_provenance(self, config_dir: Path, tmp_path: Path) -> None:
        """A machine-specific override must never be invisible."""
        settings = load_settings(
            config_dir=config_dir,
            environ={"PROSPECTING__LOG__LEVEL": "DEBUG"},
            project_root=tmp_path,
        )
        assert settings.meta.environment_overrides == ("PROSPECTING__LOG__LEVEL",)

    def test_list_valued_override(self, config_dir: Path, tmp_path: Path) -> None:
        settings = load_settings(
            config_dir=config_dir,
            environ={"PROSPECTING__ICP__PRIORITY_COUNTRIES": '["US","CA"]'},
            project_root=tmp_path,
        )
        assert settings.icp.priority_countries == frozenset({"US", "CA"})

    def test_boolean_override(self, config_dir: Path, tmp_path: Path) -> None:
        settings = load_settings(
            config_dir=config_dir,
            environ={"PROSPECTING__BUDGET__ENABLED": "false"},
            project_root=tmp_path,
        )
        assert settings.budget.enabled is False

    def test_unrelated_environment_variables_are_ignored(
        self, config_dir: Path, tmp_path: Path
    ) -> None:
        settings = load_settings(
            config_dir=config_dir,
            environ={"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "secret"},
            project_root=tmp_path,
        )
        assert settings.meta.environment_overrides == ()

    def test_config_dir_can_come_from_the_environment(
        self, config_dir: Path, tmp_path: Path
    ) -> None:
        settings = load_settings(
            environ={"PROSPECTING_CONFIG_DIR": str(config_dir)},
            project_root=tmp_path,
        )
        assert settings.paths.config_dir == config_dir


class TestValidationReporting:
    def test_reports_every_problem_at_once(self, config_dir: Path, tmp_path: Path) -> None:
        """One pass should be enough to fix a broken file."""
        broken = MINIMAL_RUNTIME.replace(
            "max_concurrent_requests: 8", "max_concurrent_requests: 0"
        ).replace("max_attempts: 3", "max_attempts: 0")
        (config_dir / "runtime.yaml").write_text(broken, encoding="utf-8")

        with pytest.raises(ConfigValidationError) as exc_info:
            load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)

        assert len(exc_info.value.problems) >= 2
        joined = " ".join(exc_info.value.problems)
        assert "runtime.max_concurrent_requests" in joined
        assert "retry.max_attempts" in joined

    def test_names_the_files_that_produced_the_failure(
        self, config_dir: Path, tmp_path: Path
    ) -> None:
        (config_dir / "runtime.yaml").write_text(
            MINIMAL_RUNTIME.replace("max_attempts: 3", "max_attempts: 0"), encoding="utf-8"
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)
        assert config_dir / "runtime.yaml" in exc_info.value.sources

    def test_unknown_key_is_reported_as_a_typo(self, config_dir: Path, tmp_path: Path) -> None:
        (config_dir / "runtime.yaml").write_text(
            MINIMAL_RUNTIME + "  max_concurent_requests: 4\n", encoding="utf-8"
        )
        with pytest.raises(ConfigValidationError, match="unknown setting"):
            load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)

    def test_business_rule_violation_is_reported(self, config_dir: Path, tmp_path: Path) -> None:
        """Weights that no longer total 100 must not reach a scoring run."""
        (config_dir / "icp.yaml").write_text(
            MINIMAL_ICP.replace("exhibition_history: 30.0", "exhibition_history: 45.0"),
            encoding="utf-8",
        )
        with pytest.raises(ConfigValidationError, match="sum to 100"):
            load_settings(config_dir=config_dir, environ={}, project_root=tmp_path)


class TestShippedConfiguration:
    """The committed configuration must itself be valid.

    Without this, a bad edit to config/*.yaml is discovered by the first person
    to start a run rather than by the test suite.
    """

    def test_baseline_configuration_loads(self) -> None:
        settings = load_settings(environ={})
        assert settings.icp.rubric_version
        assert settings.runtime.max_concurrent_requests >= 1

    @pytest.mark.parametrize("profile", ["dev", "test"])
    def test_shipped_profiles_load(self, profile: str) -> None:
        settings = load_settings(profile=profile, environ={})
        assert settings.meta.profile == profile

    def test_manifest_matches_the_files_on_disk(self) -> None:
        config_root = resolve_project_root() / "config"
        for filename in CONFIG_FILES:
            assert (config_root / filename).is_file(), f"{filename} is in CONFIG_FILES but absent"

    def test_priority_countries_match_the_ideal_artist_profile(self) -> None:
        """The 20 markets named in the approved ICP document."""
        settings = load_settings(environ={})
        assert settings.icp.priority_countries == frozenset(
            {
                "US",
                "CA",
                "GB",
                "FR",
                "DE",
                "IT",
                "ES",
                "NL",
                "BE",
                "CH",
                "AT",
                "DK",
                "SE",
                "NO",
                "FI",
                "IE",
                "LU",
                "AU",
                "NZ",
                "AE",
                "QA",
            }
        )
