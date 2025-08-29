import math
import pytest
from hypothesis import given, strategies as st

from ibkr_etf_rebalancer import AccountSnapshot, compute_account_state


def test_weights_and_exposure_with_and_without_cash_buffer():
    positions = {"SPY": 10, "GLD": 5}
    prices = {"SPY": 100.0, "GLD": 200.0}
    cash = {"USD": 1000.0, "CAD": 500.0}

    no_buf = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
    buf = compute_account_state(positions, prices, cash, cash_buffer_pct=10.0)

    # Without buffer ---------------------------------------------------------
    assert isinstance(no_buf, AccountSnapshot)
    assert pytest.approx(1_000 / 3_000, rel=1e-6) == no_buf.weights["SPY"]
    assert pytest.approx(1_000 / 3_000, rel=1e-6) == no_buf.weights["GLD"]
    assert pytest.approx(1_000 / 3_000, rel=1e-6) == no_buf.weights["CASH"]
    assert pytest.approx(2_000 / 3_000, rel=1e-6) == no_buf.gross_exposure
    assert pytest.approx(1.0, rel=1e-6) == no_buf.net_exposure
    assert "CAD" not in no_buf.weights
    assert pytest.approx(500.0, rel=1e-6) == no_buf.cad_cash
    assert pytest.approx(3_000.0, rel=1e-6) == no_buf.total_equity
    assert pytest.approx(3_000.0, rel=1e-6) == no_buf.effective_equity

    # With 10% buffer --------------------------------------------------------
    assert pytest.approx(1_000 / 2_900, rel=1e-6) == buf.weights["SPY"]
    assert pytest.approx(1_000 / 2_900, rel=1e-6) == buf.weights["GLD"]
    assert pytest.approx(900 / 2_900, rel=1e-6) == buf.weights["CASH"]
    assert pytest.approx(2_000 / 2_900, rel=1e-6) == buf.gross_exposure
    assert pytest.approx(1.0, rel=1e-6) == buf.net_exposure
    assert pytest.approx(500.0, rel=1e-6) == buf.cad_cash
    assert pytest.approx(3_000.0, rel=1e-6) == buf.total_equity
    assert pytest.approx(2_900.0, rel=1e-6) == buf.effective_equity

    # weights sum to unity within tolerance
    assert abs(sum(buf.weights.values()) - 1.0) < 1e-6


def test_cash_only_account():
    positions: dict[str, float] = {}
    prices: dict[str, float] = {}
    cash = {"USD": 2500.0, "CAD": 0.0}

    result = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
    assert result.market_values == {}
    assert result.weights == {"CASH": 1.0}
    assert pytest.approx(0.0, rel=1e-6) == result.gross_exposure
    assert pytest.approx(1.0, rel=1e-6) == result.net_exposure
    assert pytest.approx(2500.0, rel=1e-6) == result.usd_cash
    assert pytest.approx(2_500.0, rel=1e-6) == result.total_equity
    assert pytest.approx(2_500.0, rel=1e-6) == result.effective_equity


def test_snapshot_only_includes_targets_and_existing_positions():
    positions = {"SPY": 10, "XYZ": 5}
    prices = {"SPY": 100.0, "GLD": 200.0, "XYZ": 50.0, "ABC": 75.0}
    cash = {"USD": 0.0}
    _final_targets = {"SPY", "GLD"}

    snapshot = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)

    assert "SPY" in snapshot.weights
    assert "XYZ" in snapshot.weights  # existing position not in final targets
    assert "GLD" not in snapshot.weights  # targeted but no position
    assert "ABC" not in snapshot.weights  # neither targeted nor held


def test_weights_use_netliq_minus_cash_buffer_amount():
    positions = {"SPY": 10}
    prices = {"SPY": 100.0}
    cash = {"USD": 100.0}

    snapshot = compute_account_state(positions, prices, cash, cash_buffer_pct=20.0)

    netliq = 1_000 + 100
    buffer_amount = 100 * (20.0 / 100.0)
    denom = netliq - buffer_amount

    assert pytest.approx(1_000 / denom, rel=1e-6) == snapshot.weights["SPY"]
    assert pytest.approx((100 - buffer_amount) / denom, rel=1e-6) == snapshot.weights["CASH"]


@pytest.mark.parametrize(
    "positions, prices, cad_cash",
    [
        ({"SPY": 10}, {"SPY": 100.0}, 1_000.0),
        ({"SPY": 10, "GLD": 5}, {"SPY": 100.0, "GLD": 200.0}, 2_500.0),
    ],
)
def test_cad_cash_is_ignored_in_weights(positions, prices, cad_cash):
    cash = {"USD": 0.0, "CAD": cad_cash}
    snapshot = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)

    assert "CAD" not in snapshot.weights
    assert pytest.approx(0.0, abs=1e-6) == snapshot.weights["CASH"]
    assert abs(sum(snapshot.weights.values()) - 1.0) < 1e-6
    assert pytest.approx(cad_cash, rel=1e-6) == snapshot.cad_cash
    total_mv = sum(qty * prices[sym] for sym, qty in positions.items())
    assert pytest.approx(total_mv, rel=1e-6) == snapshot.total_equity
    assert pytest.approx(total_mv, rel=1e-6) == snapshot.effective_equity


@pytest.mark.parametrize(
    "positions, prices, usd_cash",
    [
        (
            {"GLD": 10, "GDX": 20},
            {"GLD": 180.0, "GDX": 40.0},
            1_000.0,
        ),
        (
            {"GLD": 5, "GDX": 10},
            {"GLD": 180.0, "GDX": 40.0},
            0.0,
        ),
    ],
)
def test_overlapping_etfs_market_values_and_weights(positions, prices, usd_cash):
    cash = {"USD": usd_cash}
    snapshot = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)

    expected_market_values = {sym: qty * prices[sym] for sym, qty in positions.items()}
    for sym, mv in expected_market_values.items():
        assert pytest.approx(mv, rel=1e-6) == snapshot.market_values[sym]

    total_equity = sum(expected_market_values.values()) + usd_cash
    for sym, mv in expected_market_values.items():
        assert pytest.approx(mv / total_equity, rel=1e-6) == snapshot.weights[sym]
    assert pytest.approx(usd_cash / total_equity, rel=1e-6) == snapshot.weights["CASH"]
    assert abs(sum(snapshot.weights.values()) - 1.0) < 1e-6


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


def test_negative_quantity_raises():
    positions = {"SPY": -10}
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


# ---------------------------------------------------------------------------
# Hypothesis based tests


@st.composite
def portfolios(draw):
    symbols = draw(
        st.lists(
            st.sampled_from(["AAA", "BBB", "CCC", "DDD", "EEE"]),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    positions = {}
    prices = {}
    for sym in symbols:
        positions[sym] = draw(
            st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False)
        )
        prices[sym] = draw(
            st.floats(min_value=0.01, max_value=1_000.0, allow_nan=False, allow_infinity=False)
        )
    usd_cash = draw(
        st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
    )
    cad_cash = draw(
        st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
    )
    return positions, prices, {"USD": usd_cash, "CAD": cad_cash}


@given(portfolios())
def test_weights_sum_to_unity_excluding_cash(portfolio):
    positions, prices, cash = portfolio
    snapshot = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
    cash_weight = snapshot.weights["CASH"]
    asset_weight_sum = sum(w for s, w in snapshot.weights.items() if s != "CASH")
    assert math.isclose(asset_weight_sum / (1.0 - cash_weight), 1.0, rel_tol=1e-6)


@given(portfolios())
def test_market_values_non_negative(portfolio):
    positions, prices, cash = portfolio
    snapshot = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
    assert all(v >= 0.0 for v in snapshot.market_values.values())


def test_negative_usd_cash_reflects_leverage():
    positions = {"SPY": 200}
    prices = {"SPY": 100.0}
    cash = {"USD": -10_000.0, "CAD": 0.0}

    snapshot = compute_account_state(positions, prices, cash, cash_buffer_pct=0.0)
    assert snapshot.weights["SPY"] > 1.0
    assert snapshot.weights["CASH"] < 0.0
    assert pytest.approx(2.0, rel=1e-6) == snapshot.gross_exposure
    assert pytest.approx(1.0, rel=1e-6) == snapshot.net_exposure
