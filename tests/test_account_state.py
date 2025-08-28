import math
import pytest

from ibkr_etf_rebalancer.account_state import compute_account_state


def test_weights_and_exposure_with_and_without_cash_buffer():
    positions = {"SPY": 10, "GLD": 5}
    prices = {"SPY": 100.0, "GLD": 200.0}
    cash = {"USD": 1000.0, "CAD": 500.0}

    no_buf = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
    buf = compute_account_state(positions, prices, cash, cash_buffer_pct=0.1)

    # Without buffer ---------------------------------------------------------
    assert pytest.approx(1_000 / 3_000, rel=1e-6) == no_buf.weights["SPY"]
    assert pytest.approx(1_000 / 3_000, rel=1e-6) == no_buf.weights["GLD"]
    assert pytest.approx(2_000 / 3_000, rel=1e-6) == no_buf.gross_exposure
    assert pytest.approx(1.0, rel=1e-6) == no_buf.net_exposure
    assert "CAD" not in no_buf.weights
    assert pytest.approx(500.0, rel=1e-6) == no_buf.cad_cash

    # With 10% buffer --------------------------------------------------------
    assert pytest.approx(1_000 / 2_900, rel=1e-6) == buf.weights["SPY"]
    assert pytest.approx(1_000 / 2_900, rel=1e-6) == buf.weights["GLD"]
    assert pytest.approx(2_000 / 2_900, rel=1e-6) == buf.gross_exposure
    assert pytest.approx(1.0, rel=1e-6) == buf.net_exposure
    assert pytest.approx(500.0, rel=1e-6) == buf.cad_cash


def test_cash_only_account():
    positions: dict[str, float] = {}
    prices: dict[str, float] = {}
    cash = {"USD": 2500.0, "CAD": 0.0}

    result = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
    assert result.weights == {}
    assert pytest.approx(0.0, rel=1e-6) == result.gross_exposure
    assert pytest.approx(1.0, rel=1e-6) == result.net_exposure
    assert pytest.approx(2500.0, rel=1e-6) == result.usd_cash


@pytest.mark.parametrize(
    "prices",
    [
        {},
        {"SPY": 0.0},
        {"SPY": math.nan},
    ],
)
def test_invalid_prices_raise(prices):
    positions = {"SPY": 10}
    cash = {"USD": 0.0}
    with pytest.raises(ValueError):
        compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)


def test_zero_quantity_raises():
    positions = {"SPY": 0}
    prices = {"SPY": 100.0}
    cash = {"USD": 0.0}
    with pytest.raises(ValueError):
        compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)


def test_no_positions_raises():
    positions: dict[str, float] = {}
    prices: dict[str, float] = {}
    cash = {"USD": 0.0}
    with pytest.raises(ValueError):
        compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
