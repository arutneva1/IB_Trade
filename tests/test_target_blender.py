import sys
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from ibkr_etf_rebalancer.target_blender import blend_targets
from ibkr_etf_rebalancer.config import ModelsConfig

# Ensure the package root is on the import path when running tests directly
sys.path.append(str(Path(__file__).resolve().parents[1]))

# Strategies -----------------------------------------------------------------


@st.composite
def model_weights(draw):
    w1 = draw(st.floats(min_value=0.0, max_value=1.0))
    w2 = draw(st.floats(min_value=0.0, max_value=1.0 - w1))
    w3 = 1.0 - w1 - w2
    return ModelsConfig(SMURF=w1, BADASS=w2, GLTR=w3)


SYMBOLS = ["AAA", "BBB", "CCC", "DDD"]


@st.composite
def random_portfolio(draw, require_symbol: str | None = None):
    include_cash = draw(st.booleans())
    num_assets = draw(st.integers(min_value=1, max_value=3))
    available = [s for s in SYMBOLS if s != require_symbol]
    symbols = draw(
        st.lists(st.sampled_from(available), min_size=num_assets, max_size=num_assets, unique=True)
    )
    if require_symbol is not None:
        symbols = [require_symbol] + symbols
    weights = draw(
        st.lists(
            st.floats(min_value=0.01, max_value=0.9),
            min_size=len(symbols),
            max_size=len(symbols),
        )
    )
    asset_sum = sum(weights)
    if include_cash:
        factor = draw(st.floats(min_value=1.0001, max_value=1.5)) / asset_sum
        weights = [w * factor for w in weights]
        asset_sum = sum(weights)
        cash = 1.0 - asset_sum
        portfolio = {sym: w for sym, w in zip(symbols, weights)}
        portfolio["CASH"] = cash
    else:
        factor = 1.0 / asset_sum
        weights = [w * factor for w in weights]
        portfolio = {sym: w for sym, w in zip(symbols, weights)}
    return portfolio


@st.composite
def portfolios(draw, require_symbol: str | None = None):
    return {
        "SMURF": draw(random_portfolio(require_symbol=require_symbol)),
        "BADASS": draw(random_portfolio(require_symbol=require_symbol)),
        "GLTR": draw(random_portfolio(require_symbol=require_symbol)),
    }


# Property tests -------------------------------------------------------------


@given(portfolios(), model_weights())
def test_blend_normalizes_to_one(portfolios, weights):
    result = blend_targets(portfolios, weights)
    assert pytest.approx(1.0, abs=1e-9) == result.net_exposure
    assert pytest.approx(1.0, abs=1e-9) == sum(result.weights.values())
    # Deterministic ordering
    assert list(result.weights.keys()) == sorted(result.weights.keys())


@given(portfolios(require_symbol="SPY"), model_weights())
def test_overlapping_symbols_are_combined(portfolios, weights):
    result = blend_targets(portfolios, weights)
    # Compute expected SPY weight
    raw_spy = sum(
        weights_dict.get("SPY", 0.0) * getattr(weights, model)
        for model, weights_dict in portfolios.items()
    )
    raw_total = sum(
        sum(wts.values()) * getattr(weights, model) for model, wts in portfolios.items()
    )
    expected_spy = raw_spy / raw_total
    assert pytest.approx(expected_spy, rel=1e-9, abs=1e-9) == result.weights["SPY"]
    # Only one SPY entry after blending
    assert list(result.weights.keys()).count("SPY") == 1
