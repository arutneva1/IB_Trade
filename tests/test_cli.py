"""Integration tests for the Typer CLI."""

from pathlib import Path
from datetime import datetime, timezone
import json
import re
import subprocess

import pytest
from freezegun import freeze_time
from typer.testing import CliRunner

from ibkr_etf_rebalancer.app import app
import ibkr_etf_rebalancer.app as app_module
from ibkr_etf_rebalancer.ibkr_provider import (
    AccountValue,
    Contract,
    FakeIB,
    IBKRProviderOptions,
    Position,
)
from ibkr_etf_rebalancer.pricing import Quote


runner = CliRunner()


def test_entry_point_help() -> None:
    result = subprocess.run(
        [
            "ib-rebalance",
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Utilities for running pre-trade reports and scenarios" in result.stdout


_ORDER_RE = re.compile(
    r"Contract\(symbol='(?P<symbol>[^']+)', sec_type='(?P<sec_type>[^']+)', currency='(?P<currency>[^']+)'"
)
_SIDE_RE = re.compile(r"OrderSide.(?P<side>BUY|SELL)")


def _parse_order(text: str) -> dict[str, str]:
    m = _ORDER_RE.search(text)
    if not m:
        raise AssertionError(f"cannot parse order: {text}")
    side = _SIDE_RE.search(text)
    return {"symbol": m.group("symbol"), "side": side.group("side") if side else ""}


def _write_basic_files(tmp_path: Path, report_dir: Path | None = None) -> tuple[Path, Path, Path]:
    config = tmp_path / "config.ini"
    config.write_text(
        "[ibkr]\n"
        "account = DU123\n\n"
        "[models]\n"
        "SMURF = 0.5\n"
        "BADASS = 0.3\n"
        "GLTR = 0.2\n\n"
        "[rebalance]\n"
        "cash_buffer_pct = 0\n\n"
        "[fx]\n"
        "[limits]\n"
        "[safety]\n"
        "[io]\n"
        f"{'report_dir = ' + str(report_dir) + '\n' if report_dir else ''}"
    )

    portfolios = tmp_path / "portfolios.csv"
    portfolios.write_text(
        """portfolio,symbol,target_pct\nSMURF,AAA,60\nSMURF,BBB,40\nBADASS,AAA,60\nBADASS,BBB,40\nGLTR,AAA,60\nGLTR,BBB,40\n"""
    )

    positions = tmp_path / "positions.csv"
    positions.write_text("""symbol,quantity,price\nAAA,500,100\nBBB,625,80\n""")

    return config, portfolios, positions


def _write_rebalance_files(tmp_path: Path, report_dir: Path | None = None) -> tuple[Path, Path]:
    config = tmp_path / "config.ini"
    config.write_text(
        "[ibkr]\n"
        "account = DU123\n\n"
        "[models]\n"
        "SMURF = 0.5\n"
        "BADASS = 0.3\n"
        "GLTR = 0.2\n\n"
        "[rebalance]\n"
        "cash_buffer_pct = 0\n"
        "min_order_usd = 0.01\n\n"
        "[fx]\n"
        "enabled = true\n"
        "base_currency = USD\n"
        "funding_currencies = CAD\n"
        "wait_for_fill_seconds = 0\n"
        "min_fx_order_usd = 10\n\n"
        "[limits]\n"
        "[safety]\n"
        "[io]\n"
        f"{'report_dir = ' + str(report_dir) + '\n' if report_dir else ''}"
    )

    portfolios = tmp_path / "portfolios.csv"
    portfolios.write_text(
        """portfolio,symbol,target_pct\nSMURF,AAA,50\nSMURF,BBB,50\nBADASS,AAA,50\nBADASS,BBB,50\nGLTR,AAA,50\nGLTR,BBB,50\n"""
    )

    return config, portfolios


def _fake_ib() -> FakeIB:
    now = datetime(2024, 1, 1, 15, 0, 0, tzinfo=timezone.utc)
    contracts = {
        "AAA": Contract(symbol="AAA"),
        "BBB": Contract(symbol="BBB"),
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    quotes = {
        "AAA": Quote(bid=99.0, ask=101.0, ts=now),
        "BBB": Quote(bid=49.0, ask=51.0, ts=now),
        "USD": Quote(bid=1.34, ask=1.36, ts=now),
    }
    positions = [
        Position(account="DU123", contract=contracts["AAA"], quantity=0, avg_price=100.0),
        Position(account="DU123", contract=contracts["BBB"], quantity=50, avg_price=50.0),
    ]
    account_values = [
        AccountValue(tag="CashBalance", value=0.0, currency="USD"),
        AccountValue(tag="CashBalance", value=1000.0, currency="CAD"),
    ]
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True),
        contracts=contracts,
        quotes=quotes,
        account_values=account_values,
        positions=positions,
    )
    ib.connect()
    return ib


def test_pre_trade_cli(tmp_path: Path) -> None:
    config, portfolios, positions = _write_basic_files(tmp_path, report_dir=tmp_path)

    with freeze_time("2024-01-01 12:00:00"):
        result = runner.invoke(
            app,
            [
                "pre-trade",
                "--config",
                str(config),
                "--portfolios",
                str(portfolios),
                "--positions",
                str(positions),
                "--cash",
                "USD=0",
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    csv = tmp_path / "pre_trade_report_20240101T120000.csv"
    md = tmp_path / "pre_trade_report_20240101T120000.md"
    assert csv.exists()
    assert md.exists()
    log = tmp_path / "run_20240101T120000.log"
    assert log.exists()


@pytest.mark.parametrize(
    "flag",
    ["--report-only", "--dry-run", "--paper", "--live", "--yes"],
)
def test_pre_trade_cli_global_flags(tmp_path: Path, flag: str) -> None:
    """Ensure top-level flags are accepted by the CLI."""

    config, portfolios, positions = _write_basic_files(tmp_path)

    with freeze_time("2024-01-01 12:00:00"):
        result = runner.invoke(
            app,
            [
                flag,
                "pre-trade",
                "--config",
                str(config),
                "--portfolios",
                str(portfolios),
                "--positions",
                str(positions),
                "--cash",
                "USD=0",
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0


def test_scenario_flag(tmp_path: Path) -> None:
    """Running with --scenario executes the scenario runner."""
    fixture = Path(__file__).resolve().parent / "e2e/fixtures/no_trade_within_band.yml"
    scenario_path = tmp_path / "scenario.yml"
    scenario_path.write_text(fixture.read_text().replace("min_order_usd: 0", "min_order_usd: 1e-9"))
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["--yes", "--scenario", str(scenario_path)])
        assert result.exit_code == 0
        report_dir = Path("reports")
        csv = report_dir / "pre_trade_report_20240101T100000.csv"
        md = report_dir / "pre_trade_report_20240101T100000.md"
        assert csv.exists()
        assert md.exists()


@pytest.mark.parametrize("flag", ["--no-paper", "--live"])
def test_scenario_forces_paper(tmp_path: Path, flag: str) -> None:
    """Scenario flag should ignore live/paper toggles and still run."""
    fixture = Path(__file__).resolve().parent / "e2e/fixtures/no_trade_within_band.yml"
    scenario_path = tmp_path / "scenario.yml"
    scenario_path.write_text(fixture.read_text().replace("min_order_usd: 0", "min_order_usd: 1e-9"))
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["--yes", flag, "--scenario", str(scenario_path)])
        assert result.exit_code == 0
        report_dir = Path("reports")
        csv = report_dir / "pre_trade_report_20240101T100000.csv"
        md = report_dir / "pre_trade_report_20240101T100000.md"
        assert csv.exists()
        assert md.exists()


def test_rebalance_cli_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, portfolios = _write_rebalance_files(tmp_path, report_dir=tmp_path)
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "--yes",
                "rebalance",
                "--config",
                str(config),
                "--portfolios",
                str(portfolios),
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0
    log = tmp_path / "run_20240101T150000.log"
    assert log.exists()


@pytest.mark.parametrize("flag", ["--no-paper", "--live"])
def test_rebalance_cli_paper_live_gating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    config, portfolios = _write_rebalance_files(tmp_path)
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--yes",
                flag,
                "rebalance",
                "--config",
                str(config),
                "--portfolios",
                str(portfolios),
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code != 0


def test_rebalance_cli_event_log_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, portfolios = _write_rebalance_files(tmp_path)
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--yes",
                "rebalance",
                "--config",
                str(config),
                "--portfolios",
                str(portfolios),
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0
    events = json.loads((tmp_path / "event_log_20240101T150000.json").read_text())
    placed = [_parse_order(e["order"]) for e in events if e["type"] == "placed"]
    assert [p["symbol"] for p in placed] == ["USD", "BBB", "AAA"]
    assert [p["side"] for p in placed] == ["BUY", "SELL", "BUY"]


def test_log_level_toggle(tmp_path: Path) -> None:
    config, portfolios, positions = _write_basic_files(tmp_path, report_dir=tmp_path)

    with freeze_time("2024-01-01 12:00:00"):
        result = runner.invoke(
            app,
            [
                "pre-trade",
                "--config",
                str(config),
                "--portfolios",
                str(portfolios),
                "--positions",
                str(positions),
                "--cash",
                "USD=0",
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0
    log = tmp_path / "run_20240101T120000.log"
    assert "CLI options" not in log.read_text()

    with freeze_time("2024-01-01 12:00:01"):
        result = runner.invoke(
            app,
            [
                "--log-level",
                "DEBUG",
                "pre-trade",
                "--config",
                str(config),
                "--portfolios",
                str(portfolios),
                "--positions",
                str(positions),
                "--cash",
                "USD=0",
                "--output-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0
    log2 = tmp_path / "run_20240101T120001.log"
    assert "CLI options" in log2.read_text()
