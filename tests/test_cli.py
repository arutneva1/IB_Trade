"""CLI integration tests."""

from typer.testing import CliRunner

from ibkr_etf_rebalancer.app import app


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
