import sys
from pathlib import Path

import pytest
from freezegun import freeze_time

from ibkr_etf_rebalancer.reporting import (
    generate_post_trade_report,
    generate_pre_trade_report,
)

# Ensure project root on path for direct test execution
sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_pre_trade_report(tmp_path):
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 80.0}

    with freeze_time("2024-01-01 12:00:00"):
        _, csv_path, md_path = generate_pre_trade_report(
            targets, current, prices, 100_000.0, output_dir=tmp_path
        )

    golden_csv = Path("tests/golden/pre_trade_report.csv").read_text()
    golden_md = Path("tests/golden/pre_trade_report.md").read_text()

    assert csv_path.read_text() == golden_csv
    assert md_path.read_text() == golden_md


def test_post_trade_report():
    executions = [
        {
            "symbol": "AAA",
            "side": "BUY",
            "filled_shares": 100.0,
            "avg_price": 10.0,
        },
        {
            "symbol": "BBB",
            "side": "SELL",
            "filled_shares": -50.0,
            "avg_price": 20.0,
        },
    ]

    df = generate_post_trade_report(executions)

    expected_cols = [
        "symbol",
        "side",
        "filled_shares",
        "avg_price",
        "notional",
    ]
    assert list(df.columns) == expected_cols
    assert df.loc[0, "notional"] == pytest.approx(1000.0)
    assert df.loc[1, "notional"] == pytest.approx(-1000.0)
    assert df["filled_shares"].sum() == pytest.approx(50.0)
    assert df["notional"].sum() == pytest.approx(0.0)

    golden_csv = Path("tests/golden/post_trade_report.csv").read_text()
    assert df.to_csv(index=False) == golden_csv
