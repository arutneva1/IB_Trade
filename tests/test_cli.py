"""Integration tests for the Typer CLI."""

from pathlib import Path
from datetime import datetime, timezone
import json
import re
import subprocess

import pytest
from freezegun import freeze_time
from typer.testing import CliRunner
from click.testing import Result

from ibkr_etf_rebalancer.app import app
import ibkr_etf_rebalancer.app as app_module
from ibkr_etf_rebalancer import limit_pricer
from ibkr_etf_rebalancer.reporting import generate_pre_trade_report
from ibkr_etf_rebalancer.ibkr_provider import (
    AccountValue,
    Contract,
    FakeIB,
    IBKRProviderOptions,
    Position,
)
from ibkr_etf_rebalancer.pricing import Quote
from ibkr_etf_rebalancer.errors import (
    ConfigError,
    SafetyError,
    RuntimeError,
    UnknownError,
    ExitCode,
)


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
    report_dir_line = f"report_dir = {report_dir}\n" if report_dir else ""
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
        "[io]\n" + report_dir_line
    )

    portfolios = tmp_path / "portfolios.csv"
    portfolios.write_text(
        """portfolio,symbol,target_pct\nSMURF,AAA,60\nSMURF,BBB,40\nBADASS,AAA,60\nBADASS,BBB,40\nGLTR,AAA,60\nGLTR,BBB,40\n"""
    )

    positions = tmp_path / "positions.csv"
    positions.write_text("""symbol,quantity,price\nAAA,500,100\nBBB,625,80\n""")

    return config, portfolios, positions


def _write_rebalance_files(
    tmp_path: Path, report_dir: Path | None = None, paper_only: bool = True
) -> tuple[Path, Path]:
    config = tmp_path / "config.ini"
    report_dir_line = f"report_dir = {report_dir}\n" if report_dir else ""
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
        f"paper_only = {'true' if paper_only else 'false'}\n"
        "[io]\n" + report_dir_line
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


def test_pre_trade_cli_json_logging(tmp_path: Path) -> None:
    """CLI writes JSON formatted logs when --log-json is used."""

    config, portfolios, positions = _write_basic_files(tmp_path, report_dir=tmp_path)

    with freeze_time("2024-01-01 12:00:00"):
        result = runner.invoke(
            app,
            [
                "--log-json",
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
    assert log.exists()
    entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert entries
    run_id = entries[0]["run_id"]
    assert run_id == "20240101T120000"
    for entry in entries:
        assert {"time", "level", "run_id", "message"} <= entry.keys()
        assert entry["run_id"] == run_id
        # time is ISO formatted and parseable
        datetime.strptime(entry["time"], "%Y-%m-%dT%H:%M:%S%z")


def test_pre_trade_cli_as_of(tmp_path: Path) -> None:
    config, portfolios, positions = _write_basic_files(tmp_path, report_dir=tmp_path)

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
            "--as-of",
            "2024-02-01T10:30:00",
        ],
    )

    assert result.exit_code == 0
    csv = tmp_path / "pre_trade_report_20240201T103000.csv"
    md = tmp_path / "pre_trade_report_20240201T103000.md"
    log = tmp_path / "run_20240201T103000.log"
    assert csv.exists()
    assert md.exists()
    assert log.exists()


@pytest.mark.parametrize("log_json", [False, True])
def test_pre_trade_cli_log_redaction(tmp_path: Path, log_json: bool) -> None:
    config, portfolios, positions = _write_basic_files(tmp_path, report_dir=tmp_path)

    args = [
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
    ]
    if log_json:
        args.insert(0, "--log-json")

    with freeze_time("2024-01-01 12:00:00"):
        result = runner.invoke(app, args)

    assert result.exit_code == 0
    log = tmp_path / "run_20240101T120000.log"
    text = log.read_text()
    assert "account" in text
    assert "DU123" not in text
    assert "localhost" not in text
    assert "7497" not in text


@pytest.mark.parametrize(
    "flag",
    ["--report-only", "--dry-run", "--paper", "--live", "--yes", "--kill-switch"],
)
def test_pre_trade_cli_global_flags(tmp_path: Path, flag: str) -> None:
    """Ensure top-level flags are accepted by the CLI."""

    config, portfolios, positions = _write_basic_files(tmp_path)

    args = [flag]
    if flag == "--kill-switch":
        args.append(str(tmp_path / "dummy"))
    args.extend(
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
        ]
    )

    with freeze_time("2024-01-01 12:00:00"):
        result = runner.invoke(app, args)

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


@pytest.mark.parametrize("log_json", [False, True])
def test_rebalance_cli_log_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, log_json: bool
) -> None:
    config, portfolios = _write_rebalance_files(tmp_path, report_dir=tmp_path)
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())

    args = [
        "--dry-run",
        "--yes",
        "rebalance",
        "--config",
        str(config),
        "--portfolios",
        str(portfolios),
        "--output-dir",
        str(tmp_path),
    ]
    if log_json:
        args.insert(0, "--log-json")

    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(app, args)

    assert result.exit_code == 0
    log = tmp_path / "run_20240101T150000.log"
    text = log.read_text()
    assert "account" in text
    assert "DU123" not in text
    assert "localhost" not in text
    assert "7497" not in text


def test_rebalance_cli_as_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
                "--as-of",
                "2024-02-01T15:00:00",
            ],
        )
    assert result.exit_code == 0
    pre_csv = tmp_path / "pre_trade_report_20240201T150000.csv"
    pre_md = tmp_path / "pre_trade_report_20240201T150000.md"
    post_csv = tmp_path / "post_trade_report_20240201T150000.csv"
    post_md = tmp_path / "post_trade_report_20240201T150000.md"
    event_log = tmp_path / "event_log_20240201T150000.json"
    log = tmp_path / "run_20240201T150000.log"
    assert pre_csv.exists()
    assert pre_md.exists()
    assert post_csv.exists()
    assert post_md.exists()
    assert event_log.exists()
    assert log.exists()


def test_rebalance_cli_no_paper_gating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, portfolios = _write_rebalance_files(tmp_path)
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--yes",
                "--no-paper",
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


def test_rebalance_cli_live_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, portfolios = _write_rebalance_files(tmp_path, report_dir=tmp_path, paper_only=False)
    kill = tmp_path / "KILL_SWITCH"
    kill.write_text("go")

    from dataclasses import replace

    def _connect(opts: IBKRProviderOptions) -> FakeIB:
        ib = _fake_ib()
        ib.options = replace(opts, allow_market_orders=True)
        return ib

    monkeypatch.setattr(app_module, "_connect_ibkr", _connect)
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--live",
                "--yes",
                "--kill-switch",
                str(kill),
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


def test_rebalance_cli_live_requires_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, portfolios = _write_rebalance_files(tmp_path, paper_only=False)
    kill = tmp_path / "KILL_SWITCH"
    kill.write_text("go")
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--live",
                "--kill-switch",
                str(kill),
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


def test_rebalance_cli_live_requires_kill_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, portfolios = _write_rebalance_files(tmp_path, paper_only=False)
    kill = tmp_path / "KILL_SWITCH"
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--live",
                "--yes",
                "--kill-switch",
                str(kill),
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


def test_rebalance_cli_kill_switch_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI kill switch option overrides config path."""

    config, portfolios = _write_rebalance_files(tmp_path, report_dir=tmp_path)
    # Engage default kill switch file
    (tmp_path / "KILL_SWITCH").write_text("stop")
    captured: dict[str, str | None] = {}

    def _connect(opts: IBKRProviderOptions) -> FakeIB:
        captured["kill_switch"] = opts.kill_switch
        return _fake_ib()

    monkeypatch.setattr(app_module, "_connect_ibkr", _connect)
    override = tmp_path / "ALT_KILL"
    with freeze_time("2024-01-01 15:00:00"):
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "--yes",
                "--kill-switch",
                str(override),
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
    assert captured["kill_switch"] == str(override)


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


def test_rebalance_cli_ask_bid_cap_toggle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, portfolios = _write_rebalance_files(tmp_path)
    monkeypatch.setattr(app_module, "_connect_ibkr", lambda opts: _fake_ib())

    captured: list[bool] = []

    orig_buy = limit_pricer.price_limit_buy
    orig_sell = limit_pricer.price_limit_sell

    def _capture_buy(quote, tick, cfg, now):
        captured.append(cfg.use_ask_bid_cap)
        return orig_buy(quote, tick, cfg, now)

    def _capture_sell(quote, tick, cfg, now):
        captured.append(cfg.use_ask_bid_cap)
        return orig_sell(quote, tick, cfg, now)

    monkeypatch.setattr(limit_pricer, "price_limit_buy", _capture_buy)
    monkeypatch.setattr(limit_pricer, "price_limit_sell", _capture_sell)

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
    assert captured and all(captured)

    captured.clear()

    with freeze_time("2024-01-01 15:00:01"):
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
                "--no-ask-bid-cap",
            ],
        )
    assert result.exit_code == 0
    assert captured and not any(captured)


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


def test_report_cli(tmp_path: Path) -> None:
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 80.0}

    with freeze_time("2024-01-01 12:00:00"):
        _, csv_path, md_path = generate_pre_trade_report(
            targets,
            current,
            prices,
            100_000.0,
            output_dir=tmp_path,
            net_liq=100_000.0,
            cash_balances={"USD": 10_000.0},
            cash_buffer=5_000.0,
        )

    result = runner.invoke(app, ["report", "--file", str(csv_path)])
    assert result.exit_code == 0
    assert "NetLiq: 100000.00" in result.stdout
    assert "AAA" in result.stdout

    md_result = runner.invoke(app, ["report", "--file", str(md_path)])
    assert md_result.exit_code == 0
    assert "NetLiq: 100000.00" in md_result.stdout
    assert "| symbol |" in md_result.stdout


def _invoke_with_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> Result:
    config, portfolios, positions = _write_basic_files(tmp_path)

    def _raise(*args: object, **kwargs: object) -> None:
        raise exc

    monkeypatch.setattr(app_module, "load_config", _raise)
    return runner.invoke(
        app,
        [
            "pre-trade",
            "--config",
            str(config),
            "--portfolios",
            str(portfolios),
            "--positions",
            str(positions),
        ],
    )


def test_cli_config_error_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke_with_exception(tmp_path, monkeypatch, ConfigError("bad config"))
    assert result.exit_code == ExitCode.CONFIG


def test_cli_safety_error_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke_with_exception(tmp_path, monkeypatch, SafetyError("nope"))
    assert result.exit_code == ExitCode.SAFETY


def test_cli_runtime_error_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke_with_exception(tmp_path, monkeypatch, RuntimeError("boom"))
    assert result.exit_code == ExitCode.RUNTIME


def test_cli_unknown_error_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke_with_exception(tmp_path, monkeypatch, UnknownError("oops"))
    assert result.exit_code == 5  # ExitCode.UNKNOWN
