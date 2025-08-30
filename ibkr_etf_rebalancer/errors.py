"""Custom exceptions and exit codes for the Typer CLI."""

from __future__ import annotations

# Specific exit codes for each error category.  These are simple integers so the
# tests and CLI can reference them without importing ``os`` on every platform.
CONFIG_IO_EXIT_CODE = 2
SAFETY_EXIT_CODE = 3
RUNTIME_EXIT_CODE = 4
UNKNOWN_EXIT_CODE = 1


class ConfigIOError(Exception):
    """Raised when configuration or I/O errors occur."""


class SafetyError(Exception):
    """Raised when a safety related issue is encountered."""


class RuntimeAppError(Exception):
    """Raised for runtime processing errors."""


class UnknownAppError(Exception):
    """Raised for unexpected errors."""

