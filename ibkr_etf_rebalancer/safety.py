"""Trading safety helpers.

This module contains small utility functions that gate potentially dangerous
operations.  They are intentionally lightweight so that they can be used in
tests without pulling in heavy dependencies.  The functions raise
``SafetyError`` when a safety condition is violated which keeps the surface
area small while still being easy to reason about in tests.
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .errors import SafetyError


def check_kill_switch(path: str | Path | None) -> None:
    """Abort if a *kill switch* file exists."""

    if path is None:
        return
    kill_switch = Path(path).expanduser()
    if kill_switch.exists():
        raise SafetyError(f"kill switch engaged: {kill_switch}")


def ensure_paper_trading(paper: bool, live: bool) -> None:
    """Ensure the application is running in paper mode."""

    if live:
        raise SafetyError("live trading explicitly requested")
    if not paper:
        raise SafetyError("not connected to paper trading environment")


def require_confirmation(msg: str, assume_yes: bool) -> None:
    """Prompt the user for confirmation.

    Parameters
    ----------
    msg:
        Message to display to the user.
    assume_yes:
        If ``True`` the confirmation is skipped.

    Raises
    ------
    SafetyError
        If the user rejects the confirmation.
    """

    if assume_yes:
        return
    answer = input(f"{msg} [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise SafetyError("confirmation rejected")


def ensure_regular_trading_hours(now: datetime, prefer_rth: bool) -> None:
    """Ensure operations occur during regular trading hours.

    ``SafetyError`` is raised when ``prefer_rth`` is ``True`` and *now*
    falls outside 09:30–16:00 Eastern on a weekday.
    """

    if not prefer_rth:
        return

    eastern = ZoneInfo("America/New_York")
    if now.tzinfo is None:
        now_eastern = now.replace(tzinfo=eastern)
    else:
        now_eastern = now.astimezone(eastern)

    if now_eastern.weekday() >= 5:
        raise SafetyError("outside regular trading hours: weekend")

    start = time(9, 30)
    end = time(16, 0)
    current = now_eastern.time()
    if not (start <= current <= end):
        raise SafetyError("outside regular trading hours: after-hours")


__all__ = [
    "check_kill_switch",
    "ensure_paper_trading",
    "require_confirmation",
    "ensure_regular_trading_hours",
]
