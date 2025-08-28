import math
import pytest
from datetime import datetime, timedelta, timezone
from hypothesis import given, settings, strategies as st, seed

from ibkr_etf_rebalancer.config import LimitsConfig
from ibkr_etf_rebalancer.pricing import Quote, FakeQuoteProvider
from ibkr_etf_rebalancer.limit_pricer import (
    price_limit_buy,
    price_limit_sell,
    calc_limit_price,
)


FIXED_NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "side,bid,ask,tick,exp",
    [
        ("BUY", 99.974, 100.026, 0.01, 100.01),
        ("BUY", 99.974, 100.026, 0.005, 100.015),
        ("SELL", 99.974, 100.026, 0.01, 99.99),
        ("SELL", 99.974, 100.026, 0.005, 99.985),
        ("BUY", 99.95, 100.05, 0.01, 100.03),
        ("SELL", 99.95, 100.05, 0.01, 99.98),
    ],
)
def test_offset_rounding(side, bid, ask, tick, exp):
    now = datetime.now(timezone.utc)
    q = Quote(bid, ask, now)
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=1000,
        wide_spread_bps=200,
        escalate_action="cross",
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    if side == "BUY":
        p, t = price_limit_buy(q, tick, cfg, now)
    else:
        p, t = price_limit_sell(q, tick, cfg, now)
    assert t == "LMT" and p == pytest.approx(exp)


@pytest.mark.parametrize(
    "side,bid,ask,maxbps,exp",
    [
        ("BUY", 100, 100.1, 1000, 100.1),
        ("SELL", 99.9, 100, 1000, 99.9),
        ("BUY", 99.9, 101, 5, 100.5),
        ("SELL", 99.9, 100.1, 5, 99.95),
    ],
)
def test_nbbo_maxoffset(side, bid, ask, maxbps, exp):
    now = datetime.now(timezone.utc)
    q = Quote(bid, ask, now)
    cfg = LimitsConfig(
        buy_offset_frac=1.0,
        sell_offset_frac=1.0,
        max_offset_bps=maxbps,
        wide_spread_bps=200,
        escalate_action="cross",
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    if side == "BUY":
        p, t = price_limit_buy(q, 0.01, cfg, now)
    else:
        p, t = price_limit_sell(q, 0.01, cfg, now)
    assert t == "LMT" and p == pytest.approx(exp)


@pytest.mark.parametrize(
    "bid,ask,delta,action,exp,t",
    [
        (99, 101, 0, "cross", 101, "LMT"),
        (99, 101, 0, "market", None, "MKT"),
        (99, 101, 0, "keep", 100.1, "LMT"),
        (99.85, 100.15, 20, "cross", 100.15, "LMT"),
        (99.85, 100.15, 20, "market", None, "MKT"),
        (99.85, 100.15, 20, "keep", 100.08, "LMT"),
    ],
)
def test_wide_or_stale_escalation(bid, ask, delta, action, exp, t):
    ts = datetime.now(timezone.utc) - timedelta(seconds=delta)
    q = Quote(bid, ask, ts)
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=10,
        wide_spread_bps=100,
        escalate_action=action,
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, ot = price_limit_buy(q, 0.01, cfg, datetime.now(timezone.utc))
    assert ot == t
    if t == "MKT":
        assert p is None
    else:
        assert p == pytest.approx(exp)


@pytest.mark.parametrize(
    "bid,ask,delta,action,exp,t",
    [
        (99, 101, 0, "cross", 99, "LMT"),
        (99, 101, 0, "market", None, "MKT"),
        (99, 101, 0, "keep", 99.9, "LMT"),
        (99.85, 100.15, 20, "cross", 99.85, "LMT"),
        (99.85, 100.15, 20, "market", None, "MKT"),
        (99.85, 100.15, 20, "keep", 99.93, "LMT"),
    ],
)
def test_sell_wide_or_stale_escalation(bid, ask, delta, action, exp, t):
    ts = datetime.now(timezone.utc) - timedelta(seconds=delta)
    q = Quote(bid, ask, ts)
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=10,
        wide_spread_bps=100,
        escalate_action=action,
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, ot = price_limit_sell(q, 0.01, cfg, datetime.now(timezone.utc))
    assert ot == t
    if t == "MKT":
        assert p is None
    else:
        assert p == pytest.approx(exp)


@pytest.mark.parametrize(
    "func,bid,ask,tick,exp",
    [
        (
            price_limit_buy,
            99.9,
            100.013,
            0.005,
            math.floor(100.013 / 0.005 + 0.5) * 0.005,
        ),
        (
            price_limit_sell,
            99.987,
            100.1,
            0.005,
            math.floor(99.987 / 0.005 + 0.5) * 0.005,
        ),
        (
            price_limit_buy,
            99.9,
            100.025,
            0.01,
            math.floor(100.025 / 0.01 + 0.5) * 0.01,
        ),
        (
            price_limit_sell,
            99.975,
            100.1,
            0.01,
            math.floor(99.975 / 0.01 + 0.5) * 0.01,
        ),
    ],
)
def test_cross_rounds_non_tick_aligned(func, bid, ask, tick, exp):
    """Cross escalation should tick align raw bid/ask prices."""
    now = datetime.now(timezone.utc)
    q = Quote(bid, ask, now)
    cfg = LimitsConfig(wide_spread_bps=0, escalate_action="cross")
    p, t = func(q, tick, cfg, now)
    assert t == "LMT" and p == pytest.approx(exp)


@pytest.mark.parametrize(
    "func,bid,ask,tick",
    [
        (price_limit_buy, 99.98, 100.006, 0.01),
        (price_limit_sell, 99.994, 100.02, 0.01),
    ],
)
def test_nbbo_cap_respected_after_rounding(func, bid, ask, tick):
    """Post-rounding price remains within the NBBO."""
    now = datetime.now(timezone.utc)
    q = Quote(bid, ask, now)
    cfg = LimitsConfig(
        buy_offset_frac=1.0,
        sell_offset_frac=1.0,
        max_offset_bps=1000,
        wide_spread_bps=200,
        escalate_action="keep",
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, t = func(q, tick, cfg, now)
    assert t == "LMT"
    if func is price_limit_buy:
        assert p <= ask
    else:
        assert p >= bid


@pytest.mark.parametrize("tick", [0.05, 0.125])
def test_buy_price_with_large_tick_stays_within_nbbo(tick):
    now = datetime.now(timezone.utc)
    ask = 100 + tick * 0.6  # non tick-aligned ask to force rounding
    bid = ask - 0.2
    q = Quote(bid, ask, now)
    cfg = LimitsConfig(
        buy_offset_frac=1.0,
        sell_offset_frac=1.0,
        max_offset_bps=1000,
        wide_spread_bps=200,
        escalate_action="keep",
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, t = price_limit_buy(q, tick, cfg, now)
    assert t == "LMT" and p <= ask


@pytest.mark.parametrize("tick", [0.05, 0.125])
def test_sell_price_with_large_tick_stays_within_nbbo(tick):
    now = datetime.now(timezone.utc)
    bid = 100 - tick * 0.6  # non tick-aligned bid to force rounding
    ask = bid + 0.2
    q = Quote(bid, ask, now)
    cfg = LimitsConfig(
        buy_offset_frac=1.0,
        sell_offset_frac=1.0,
        max_offset_bps=1000,
        wide_spread_bps=200,
        escalate_action="keep",
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, t = price_limit_sell(q, tick, cfg, now)
    assert t == "LMT" and p >= bid


def test_tick_fallback_rounding():
    now = datetime.now(timezone.utc)
    q = Quote(100.0, 100.1, now)
    p, t = price_limit_buy(q, 0, LimitsConfig(), now)
    assert t == "LMT" and p == pytest.approx(100.07)


@pytest.mark.parametrize(
    "func,bid,ask",
    [
        (price_limit_buy, None, 100),
        (price_limit_buy, 100, None),
        (price_limit_sell, None, 100),
        (price_limit_sell, 100, None),
    ],
)
def test_missing_bid_or_ask(func, bid, ask):
    now = datetime.now(timezone.utc)
    q = Quote(bid, ask, now)
    with pytest.raises(ValueError, match="missing bid/ask"):
        func(q, 0.01, LimitsConfig(), now)


def test_calc_limit_price_wrapper():
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(100, 100.1, now)})
    cfg = LimitsConfig(wide_spread_bps=1000, escalate_action="keep")
    price, t = calc_limit_price("BUY", "SYM", 0.01, provider, now, cfg)
    assert t == "LMT" and price is not None
    cfg_market = LimitsConfig(wide_spread_bps=0, escalate_action="market")
    price, t = calc_limit_price("SELL", "SYM", 0.01, provider, now, cfg_market)
    assert t == "MKT" and price is None


def test_calc_limit_price_invalid_side():
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(100, 100.1, now)})
    cfg = LimitsConfig()
    with pytest.raises(ValueError, match="BUY.*SELL"):
        calc_limit_price("HOLD", "SYM", 0.01, provider, now, cfg)


def test_calc_limit_price_smart_limit_disabled():
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(100, 100.1, now)})
    cfg = LimitsConfig(smart_limit=False)
    price, t = calc_limit_price("BUY", "SYM", 0.01, provider, now, cfg)
    assert t == "LMT" and price == 100.1
    price, t = calc_limit_price("SELL", "SYM", 0.01, provider, now, cfg)
    assert t == "LMT" and price == 100


def test_calc_limit_price_style_off():
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(100, 100.1, now)})
    cfg = LimitsConfig(style="off")
    price, t = calc_limit_price("BUY", "SYM", 0.01, provider, now, cfg)
    assert t == "LMT" and price == 100.1
    price, t = calc_limit_price("SELL", "SYM", 0.01, provider, now, cfg)
    assert t == "LMT" and price == 100


def test_calc_limit_price_style_not_supported():
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(100, 100.1, now)})
    cfg = LimitsConfig(style="static_bps")
    with pytest.raises(ValueError, match="Unsupported limit pricing style"):
        calc_limit_price("BUY", "SYM", 0.01, provider, now, cfg)


@pytest.mark.parametrize(
    "func,bid,ask",
    [
        (price_limit_buy, 100, 100),
        (price_limit_buy, 101, 100),
        (price_limit_sell, 100, 100),
        (price_limit_sell, 101, 100),
    ],
)
def test_bad_spread(func, bid, ask):
    now = datetime.now(timezone.utc)
    q = Quote(bid, ask, now)
    with pytest.raises(ValueError):
        func(q, 0.01, LimitsConfig(), now)


@seed(0)
@settings(max_examples=100, deadline=None)
@given(
    mid=st.floats(min_value=10, max_value=1000, allow_nan=False, allow_infinity=False),
    spread=st.floats(min_value=0.01, max_value=5, allow_nan=False, allow_infinity=False),
    extra=st.floats(min_value=0.0, max_value=5, allow_nan=False, allow_infinity=False),
    tick=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_spread_monotonic_and_bounds(mid, spread, extra, tick):
    wider_spread = spread + extra
    bid1 = mid - spread / 2
    ask1 = mid + spread / 2
    bid2 = mid - wider_spread / 2
    ask2 = mid + wider_spread / 2
    q1 = Quote(bid1, ask1, FIXED_NOW)
    q2 = Quote(bid2, ask2, FIXED_NOW)
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=10000,
        wide_spread_bps=100000,
        escalate_action="keep",
        stale_quote_seconds=100000,
        use_ask_bid_cap=True,
    )
    p_buy1, _ = price_limit_buy(q1, tick, cfg, FIXED_NOW)
    p_buy2, _ = price_limit_buy(q2, tick, cfg, FIXED_NOW)
    assert p_buy2 >= p_buy1
    p_sell1, _ = price_limit_sell(q1, tick, cfg, FIXED_NOW)
    p_sell2, _ = price_limit_sell(q2, tick, cfg, FIXED_NOW)
    assert p_sell2 <= p_sell1
    tick_eff = tick if tick > 0 else 0.01
    half_tick = tick_eff / 2
    assert p_buy1 <= ask1 + half_tick
    assert p_buy2 <= ask2 + half_tick
    assert p_sell1 >= bid1 - half_tick
    assert p_sell2 >= bid2 - half_tick
