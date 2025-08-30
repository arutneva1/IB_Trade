import builtins
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from ibkr_etf_rebalancer.safety import (
    check_kill_switch,
    ensure_paper_trading,
    ensure_regular_trading_hours,
    require_confirmation,
)
from ibkr_etf_rebalancer.errors import SafetyError


def test_require_confirmation_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda _: "y")
    require_confirmation("Proceed?", assume_yes=False)


def test_require_confirmation_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda _: "n")
    with pytest.raises(SafetyError):
        require_confirmation("Proceed?", assume_yes=False)


def test_check_kill_switch(tmp_path: Path) -> None:
    kill_file = tmp_path / "kill"
    kill_file.write_text("")
    with pytest.raises(SafetyError):
        check_kill_switch(kill_file)
    # Non-existent file should pass
    check_kill_switch(tmp_path / "other")


@pytest.mark.parametrize(
    "paper,live",
    [(True, True), (False, False)],
)
def test_ensure_paper_trading_guard(paper: bool, live: bool) -> None:
    with pytest.raises(SafetyError):
        ensure_paper_trading(paper=paper, live=live)


def test_ensure_regular_trading_hours_weekend() -> None:
    with freeze_time("2024-01-06 12:00:00-05:00"):
        now = datetime.now(tz=ZoneInfo("America/New_York"))
        with pytest.raises(SafetyError):
            ensure_regular_trading_hours(now, prefer_rth=True)


def test_ensure_regular_trading_hours_after_hours() -> None:
    with freeze_time("2024-01-08 17:00:00-05:00"):
        now = datetime.now(tz=ZoneInfo("America/New_York"))
        with pytest.raises(SafetyError):
            ensure_regular_trading_hours(now, prefer_rth=True)
