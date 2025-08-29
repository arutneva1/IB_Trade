from pathlib import Path

import pytest
from freezegun import freeze_time

from ibkr_etf_rebalancer.reporting import (
    generate_post_trade_report,
    generate_pre_trade_report,
)
from ibkr_etf_rebalancer.ibkr_provider import Contract, Fill, OrderSide


def test_pre_trade_report(tmp_path):
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

    golden_csv = Path("tests/golden/pre_trade_report.csv").read_text()
    golden_md = Path("tests/golden/pre_trade_report.md").read_text()

    csv_text = csv_path.read_text()
    md_text = md_path.read_text()

    assert "NetLiq" in csv_text and "Cash USD" in csv_text and "Cash Buffer" in csv_text
    assert "NetLiq" in md_text and "Cash USD" in md_text and "Cash Buffer" in md_text

    assert csv_text == golden_csv
    assert md_text == golden_md


def test_pre_trade_report_respects_min_order():
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 80.0}

    # With a large min_order the drift should be reported but no trades made
    df = generate_pre_trade_report(targets, current, prices, 100_000.0, min_order=15_000.0)

    assert (df.loc[df["symbol"] != "TOTAL", "share_delta"] == 0).all()
    assert (df.loc[df["symbol"] != "TOTAL", "est_notional"] == 0).all()


def test_post_trade_report(tmp_path):
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    prices = {"AAA": 10.0, "BBB": 20.0}

    fills = [
        Fill(contract=Contract("AAA"), side=OrderSide.BUY, quantity=100.0, price=10.0, order_id="1"),
        Fill(contract=Contract("BBB"), side=OrderSide.SELL, quantity=50.0, price=20.0, order_id="2"),
    ]
    limits = {"1": 9.5, "2": 19.5}

    with freeze_time("2024-01-01 12:00:00"):
        df, csv_path, md_path = generate_post_trade_report(
            targets,
            current,
            prices,
            100_000.0,
            fills,
            limits,
            output_dir=tmp_path,
        )

    expected_cols = [
        "symbol",
        "side",
        "filled_shares",
        "avg_price",
        "notional",
        "avg_slippage",
        "residual_drift_bps",
    ]
    assert list(df.columns) == expected_cols
    assert df.loc[0, "notional"] == pytest.approx(1000.0)
    assert df.loc[1, "notional"] == pytest.approx(-1000.0)
    assert df["filled_shares"].sum() == pytest.approx(50.0)
    assert df["notional"].sum() == pytest.approx(0.0)
    assert df.loc[df["symbol"] == "AAA", "residual_drift_bps"].iloc[0] == pytest.approx(900.0)
    assert df.loc[df["symbol"] == "BBB", "residual_drift_bps"].iloc[0] == pytest.approx(-900.0)
    assert df.loc[df["symbol"] == "AAA", "avg_slippage"].iloc[0] == pytest.approx(0.5)
    assert df.loc[df["symbol"] == "BBB", "avg_slippage"].iloc[0] == pytest.approx(-0.5)

    golden_csv = Path("tests/golden/post_trade_report.csv").read_text()
    golden_md = Path("tests/golden/post_trade_report.md").read_text()

    assert csv_path.read_text() == golden_csv
    assert md_path.read_text() == golden_md
