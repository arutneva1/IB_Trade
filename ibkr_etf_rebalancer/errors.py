"""Custom exception hierarchy and exit codes for the CLI."""
from __future__ import annotations

from enum import IntEnum


class ConfigError(Exception):
    """Configuration or IO error."""


class SafetyError(Exception):
    """Error triggered by safety checks."""


class RuntimeError(Exception):
    """Generic runtime error."""


class UnknownError(Exception):
    """Catch-all for unexpected errors."""


class ExitCode(IntEnum):
    """Exit codes for different error categories."""

    UNKNOWN = 1
    CONFIG = 2
    SAFETY = 3
    RUNTIME = 4


__all__ = [
    "ConfigError",
    "SafetyError",
    "RuntimeError",
    "UnknownError",
    "ExitCode",
]
