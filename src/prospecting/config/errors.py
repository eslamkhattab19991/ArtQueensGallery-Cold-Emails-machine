"""Configuration error hierarchy.

Every error carries the location of the problem — file path, section, key — so a
failure can be reproduced and fixed without re-running the loader under a
debugger. A configuration error that says only "invalid value" costs more time
than the validation saved.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigParseError",
    "ConfigValidationError",
    "EnvironmentOverrideError",
]


class ConfigError(Exception):
    """Base class for every configuration failure.

    Callers that want to treat all configuration problems alike — the CLI
    printing a diagnostic and exiting non-zero, for example — catch this.
    """


class ConfigFileNotFoundError(ConfigError):
    """A configuration file the loader requires does not exist."""

    def __init__(self, path: Path, *, searched_in: Path) -> None:
        """Record which file was missing and where the loader looked for it.

        Args:
            path: The absolute path that was expected to exist.
            searched_in: The configuration directory that was searched.
        """
        self.path = path
        self.searched_in = searched_in
        super().__init__(
            f"Required configuration file not found: {path}\n"
            f"  Configuration directory: {searched_in}\n"
            f"  Create the file, or point PROSPECTING_CONFIG_DIR at the correct directory."
        )


class ConfigParseError(ConfigError):
    """A configuration file exists but is not readable as YAML."""

    def __init__(self, path: Path, *, reason: str) -> None:
        """Record the unparseable file and the parser's complaint.

        Args:
            path: The file that failed to parse.
            reason: The underlying parser error message.
        """
        self.path = path
        self.reason = reason
        super().__init__(f"Could not parse configuration file: {path}\n  {reason}")


class ConfigValidationError(ConfigError):
    """The merged configuration is syntactically valid but semantically wrong.

    Raised for both type failures (a string where a number belongs) and rule
    failures (scoring weights that do not sum to 100). The message lists every
    problem found, not just the first, so a broken file can be fixed in one pass.
    """

    def __init__(self, problems: list[str], *, sources: list[Path]) -> None:
        """Record every validation problem alongside the files that produced them.

        Args:
            problems: Human-readable descriptions, one per failure.
            sources: The configuration files merged to produce the failing value.
        """
        self.problems = problems
        self.sources = sources
        source_list = "\n".join(f"    - {source}" for source in sources) or "    (none)"
        problem_list = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(
            f"Configuration is invalid ({len(problems)} problem(s)):\n"
            f"{problem_list}\n"
            f"  Merged from:\n{source_list}"
        )


class EnvironmentOverrideError(ConfigError):
    """An environment variable override could not be applied.

    Raised when a ``PROSPECTING__`` variable names a path that cannot exist in
    the configuration tree — almost always a typo, which would otherwise be
    silently ignored and leave the operator believing an override took effect.
    """

    def __init__(self, variable: str, *, reason: str) -> None:
        """Record the offending variable and why it could not be applied.

        Args:
            variable: The full environment variable name.
            reason: Why the override could not be applied.
        """
        self.variable = variable
        self.reason = reason
        super().__init__(f"Cannot apply environment override {variable!r}: {reason}")
