"""Integration tests for the Typer CLI."""

from pathlib import Path

from freezegun import freeze_time
from typer.testing import CliRunner

from ibkr_etf_rebalancer.app import app


runner = CliRunner()


def _write_basic_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    config = tmp_path / "config.ini"
    config.write_text(
        """
[ibkr]
account = DU123

[models]
SMURF = 0.5
BADASS = 0.3
GLTR = 0.2

[rebalance]
cash_buffer_pct = 0

[fx]
[limits]
[safety]
[io]
"""
    )

    portfolios = tmp_path / "portfolios.csv"
    portfolios.write_text(
        """portfolio,symbol,target_pct\nSMURF,AAA,60\nSMURF,BBB,40\nBADASS,AAA,60\nBADASS,BBB,40\nGLTR,AAA,60\nGLTR,BBB,40\n"""
    )

    positions = tmp_path / "positions.csv"
    positions.write_text("""symbol,quantity,price\nAAA,500,100\nBBB,625,80\n""")

    return config, portfolios, positions


def test_pre_trade_cli(tmp_path: Path) -> None:
    config, portfolios, positions = _write_basic_files(tmp_path)

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
