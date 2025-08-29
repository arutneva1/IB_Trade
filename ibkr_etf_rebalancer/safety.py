"""Trading safety helpers.

This module contains small utility functions that gate potentially dangerous
operations.  They are intentionally lightweight so that they can be used in
tests without pulling in heavy dependencies.  The functions raise
``RuntimeError`` when a safety condition is violated which keeps the surface
area small while still being easy to reason about in tests.
"""

from __future__ import annotations

from pathlib import Path


def check_kill_switch(path: str | Path | None) -> None:
    """Abort if a *kill switch* file exists.

    Parameters
    ----------
    path:
        Path to the kill switch file.  If ``None`` the check is skipped.

    Raises
    ------
    RuntimeError
        If the file exists.
    """

    if path is None:
        return
    if Path(path).expanduser().exists():
        raise RuntimeError("kill switch engaged")


def ensure_paper_trading(paper: bool, live: bool) -> None:
    """Ensure the application is running in paper mode.

    The function raises :class:`RuntimeError` if live trading is requested
    without explicit permission.  This is primarily used in the test
    environment where live trading should never occur.

    Parameters
    ----------
    paper:
        ``True`` when connected to a paper trading environment.
    live:
        ``True`` when live trading is explicitly requested.
    """

    if live or not paper:
        raise RuntimeError("live trading not allowed")


__all__ = ["check_kill_switch", "ensure_paper_trading"]

