"""Tests for the merge and environment-overlay primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from prospecting.config.errors import (
    ConfigFileNotFoundError,
    ConfigParseError,
    EnvironmentOverrideError,
)
from prospecting.config.sources import (
    collect_environment_overrides,
    deep_merge,
    read_yaml_file,
)


class TestReadYamlFile:
    def test_reads_a_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("runtime:\n  max_concurrent_requests: 4\n", encoding="utf-8")
        assert read_yaml_file(path, required=True) == {"runtime": {"max_concurrent_requests": 4}}

    def test_empty_file_is_an_empty_mapping(self, tmp_path: Path) -> None:
        """A comment-only file is valid and contributes nothing."""
        path = tmp_path / "c.yaml"
        path.write_text("# nothing here yet\n", encoding="utf-8")
        assert read_yaml_file(path, required=True) == {}

    def test_missing_optional_file_is_an_empty_mapping(self, tmp_path: Path) -> None:
        assert read_yaml_file(tmp_path / "absent.yaml", required=False) == {}

    def test_missing_required_file_raises_with_search_location(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigFileNotFoundError) as exc_info:
            read_yaml_file(tmp_path / "absent.yaml", required=True)
        assert exc_info.value.searched_in == tmp_path
        assert "absent.yaml" in str(exc_info.value)

    def test_malformed_yaml_raises_with_the_path(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("runtime:\n  - unclosed: [\n", encoding="utf-8")
        with pytest.raises(ConfigParseError) as exc_info:
            read_yaml_file(path, required=True)
        assert exc_info.value.path == path

    @pytest.mark.parametrize("content", ["- a\n- b\n", "just a string\n", "42\n"])
    def test_non_mapping_top_level_is_rejected(self, tmp_path: Path, content: str) -> None:
        """A list or scalar cannot be merged into the section tree."""
        path = tmp_path / "c.yaml"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigParseError, match="must be a mapping"):
            read_yaml_file(path, required=True)


class TestDeepMerge:
    def test_overlay_wins_for_scalars(self) -> None:
        assert deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_disjoint_keys_are_combined(self) -> None:
        assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_nested_mappings_merge_key_by_key(self) -> None:
        """An overlay changes one setting without restating its section."""
        base = {"runtime": {"concurrency": 8, "timeout": 30}}
        overlay = {"runtime": {"concurrency": 2}}
        assert deep_merge(base, overlay) == {"runtime": {"concurrency": 2, "timeout": 30}}

    def test_merges_to_arbitrary_depth(self) -> None:
        base = {"a": {"b": {"c": {"d": 1, "e": 2}}}}
        overlay = {"a": {"b": {"c": {"d": 9}}}}
        assert deep_merge(base, overlay) == {"a": {"b": {"c": {"d": 9, "e": 2}}}}

    def test_lists_are_replaced_not_concatenated(self) -> None:
        """Concatenation would make removing a list entry impossible."""
        base = {"countries": ["US", "GB", "FR"]}
        overlay = {"countries": ["GB"]}
        assert deep_merge(base, overlay) == {"countries": ["GB"]}

    def test_scalar_overlay_replaces_a_mapping(self) -> None:
        assert deep_merge({"a": {"b": 1}}, {"a": 5}) == {"a": 5}

    def test_mapping_overlay_replaces_a_scalar(self) -> None:
        assert deep_merge({"a": 5}, {"a": {"b": 1}}) == {"a": {"b": 1}}

    def test_explicit_none_overrides(self) -> None:
        """`key: null` is a deliberate value, not an absent one."""
        assert deep_merge({"a": 1}, {"a": None}) == {"a": None}

    def test_inputs_are_not_mutated(self) -> None:
        """Layers are merged in a chain; aliasing one into the result corrupts it."""
        base = {"runtime": {"concurrency": 8}}
        overlay = {"runtime": {"concurrency": 2}}
        deep_merge(base, overlay)
        assert base == {"runtime": {"concurrency": 8}}
        assert overlay == {"runtime": {"concurrency": 2}}

    def test_nested_result_is_not_aliased_to_the_base(self) -> None:
        base = {"runtime": {"concurrency": 8}}
        merged = deep_merge(base, {"runtime": {"timeout": 5}})
        merged["runtime"]["concurrency"] = 99
        assert base["runtime"]["concurrency"] == 8


class TestCollectEnvironmentOverrides:
    def test_ignores_unprefixed_variables(self) -> None:
        overrides, applied = collect_environment_overrides({"PATH": "/usr/bin", "HOME": "/root"})
        assert overrides == {}
        assert applied == ()

    def test_builds_a_nested_mapping(self) -> None:
        overrides, applied = collect_environment_overrides(
            {"PROSPECTING__RUNTIME__MAX_CONCURRENT_REQUESTS": "4"}
        )
        assert overrides == {"runtime": {"max_concurrent_requests": 4}}
        assert applied == ("PROSPECTING__RUNTIME__MAX_CONCURRENT_REQUESTS",)

    def test_lowercases_path_segments(self) -> None:
        overrides, _ = collect_environment_overrides({"PROSPECTING__LOG__LEVEL": "DEBUG"})
        assert overrides == {"log": {"level": "DEBUG"}}

    def test_merges_two_overrides_into_one_section(self) -> None:
        overrides, applied = collect_environment_overrides(
            {
                "PROSPECTING__LOG__LEVEL": "DEBUG",
                "PROSPECTING__LOG__FORMAT": "json",
            }
        )
        assert overrides == {"log": {"level": "DEBUG", "format": "json"}}
        assert len(applied) == 2

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("4", 4),
            ("2.5", 2.5),
            ("true", True),
            ("false", False),
            ("null", None),
            ('["GB","FR"]', ["GB", "FR"]),
            ('{"a": 1}', {"a": 1}),
        ],
    )
    def test_parses_json_values(self, raw: str, expected: object) -> None:
        overrides, _ = collect_environment_overrides({"PROSPECTING__S__K": raw})
        assert overrides["s"]["k"] == expected

    def test_non_json_values_stay_strings(self) -> None:
        """Plain words work without quoting, which is what an operator expects."""
        overrides, _ = collect_environment_overrides({"PROSPECTING__LOG__LEVEL": "DEBUG"})
        assert overrides["log"]["level"] == "DEBUG"

    def test_applied_names_are_sorted_for_determinism(self) -> None:
        _, applied = collect_environment_overrides(
            {
                "PROSPECTING__Z__K": "1",
                "PROSPECTING__A__K": "2",
            }
        )
        assert applied == ("PROSPECTING__A__K", "PROSPECTING__Z__K")

    def test_single_segment_override_is_allowed(self) -> None:
        """A top-level key is a legal, if unusual, target."""
        overrides, _ = collect_environment_overrides({"PROSPECTING__META": "x"})
        assert overrides == {"meta": "x"}

    def test_prefix_with_no_path_is_rejected(self) -> None:
        with pytest.raises(EnvironmentOverrideError, match="no setting path"):
            collect_environment_overrides({"PROSPECTING__": "x"})

    def test_doubled_separator_is_rejected(self) -> None:
        """A typo that would otherwise be silently discarded."""
        with pytest.raises(EnvironmentOverrideError, match="empty path segment"):
            collect_environment_overrides({"PROSPECTING__RUNTIME____TIMEOUT": "5"})

    def test_conflicting_shapes_are_rejected(self) -> None:
        """Two variables disagreeing about the tree shape must not resolve silently."""
        with pytest.raises(EnvironmentOverrideError, match="non-mapping value"):
            collect_environment_overrides(
                {
                    "PROSPECTING__LOG": "text",
                    "PROSPECTING__LOG__LEVEL": "DEBUG",
                }
            )
