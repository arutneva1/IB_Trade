import sys
from pathlib import Path

import pytest

from ibkr_etf_rebalancer.rebalance_engine import generate_orders

# Ensure package root on path when running tests directly
sys.path.append(str(Path(__file__).resolve().parents[1]))


PRICES = {"AAA": 100.0, "BBB": 100.0}
EQUITY = 100_000.0


def test_no_trade_when_within_band():
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.05,
        min_order=500.0,
        max_leverage=1.5,
    )
    assert orders == {}


def test_overweight_positions_generate_sells():
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    current = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert orders["AAA"] == -100


def test_underweight_positions_generate_buys():
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert orders["AAA"] == 100


def test_min_order_filtering():
    targets = {"AAA": 0.503, "BBB": 0.497, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=500.0,
        max_leverage=1.5,
    )
    assert orders == {}


def test_scaled_buy_dropped_below_min_order():
    targets = {"AAA": 0.006, "CASH": 0.0}
    current = {"AAA": 0.0, "CASH": 0.012}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=500.0,
        max_leverage=1.5,
        cash_buffer_pct=0.8,
    )
    assert orders == {}


def test_scaled_buy_dropped_below_min_order_due_to_leverage():
    targets = {"AAA": 1.006, "CASH": -0.006}
    current = {"AAA": 1.0, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=500.0,
        max_leverage=1.0,
    )
    assert orders == {}


def test_margin_leverage_scaling():
    targets = {"AAA": 1.3, "BBB": 0.3, "CASH": -0.6}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert orders["AAA"] == 700
    assert orders["BBB"] == -200


def test_fractional_buy_rounds_up():
    targets = {"AAA": 0.0012}
    current = {"AAA": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert orders["AAA"] == 2


def test_fractional_sell_rounds_away_from_zero():
    targets = {"AAA": 0.0010}
    current = {"AAA": 0.0022}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert orders["AAA"] == -2


def test_sell_rounding_drops_order_when_less_than_one_share():
    targets = {"AAA": 0.0}
    current = {"AAA": 0.0004}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert orders == {}


def test_sell_rounding_capped_at_available_shares():
    targets = {"AAA": 0.0003}
    current = {"AAA": 0.0014}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert orders["AAA"] == -1


def test_cash_buffer_limits_buys():
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        cash_buffer_pct=5.0,
        allow_fractional=False,
    )
    assert orders["BBB"] == -100
    assert orders["AAA"] == 50


def test_maintenance_buffer_limits_leverage():
    targets = {"AAA": 1.3, "BBB": 0.3, "CASH": -0.6}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        maintenance_buffer_pct=10.0,
        allow_fractional=False,
    )
    assert orders["BBB"] == -200
    assert orders["AAA"] == 600


@pytest.mark.parametrize(
    "current,expected",
    [
        ({"AAA": 0.51, "BBB": 0.49, "CASH": 0.0}, {"AAA": -10, "BBB": 10}),
        ({"AAA": 0.49, "BBB": 0.51, "CASH": 0.0}, {"AAA": 10, "BBB": -10}),
        ({"AAA": 0.505, "BBB": 0.495, "CASH": 0.0}, {}),
    ],
)
def test_total_drift_trigger_mixed_sign(current, expected):
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    orders = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.02,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
        trigger_mode="total_drift",
        portfolio_total_band_bps=100,
    )
    assert orders == expected
