import pytest
from datetime import datetime, timedelta, timezone

from ibkr_etf_rebalancer.config import LimitsConfig
from ibkr_etf_rebalancer.pricing import Quote, FakeQuoteProvider
from ibkr_etf_rebalancer.limit_pricer import (
    price_limit_buy,
    price_limit_sell,
    calc_limit_price,
)


@pytest.mark.parametrize(
    "side,bid,ask,tick,exp",
    [
        ("BUY", 99.974, 100.026, 0.01, 100.01),
        ("BUY", 99.974, 100.026, 0.005, 100.015),
        ("SELL", 99.974, 100.026, 0.01, 99.99),
        ("SELL", 99.974, 100.026, 0.005, 99.985),
    ],
)
def test_offset_rounding(side, bid, ask, tick, exp):
    now = datetime.now(timezone.utc)
    q = Quote(bid, ask, now)
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=1000,
        wide_spread_bps=100,
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
        wide_spread_bps=100,
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
        wide_spread_bps=50,
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
        (99.85, 100.15, 20, "keep", 99.92, "LMT"),
    ],
)
def test_sell_wide_or_stale_escalation(bid, ask, delta, action, exp, t):
    ts = datetime.now(timezone.utc) - timedelta(seconds=delta)
    q = Quote(bid, ask, ts)
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=10,
        wide_spread_bps=50,
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
