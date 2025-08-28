import pytest
from datetime import datetime, timedelta, timezone

from ibkr_etf_rebalancer.config import LimitsConfig
from ibkr_etf_rebalancer.pricing import Quote, FakeQuoteProvider
from ibkr_etf_rebalancer.limit_pricer import calc_limit_price


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
    prov = FakeQuoteProvider({"T": q})
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=1000,
        wide_spread_bps=100,
        escalate_action="cross",
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, t = calc_limit_price(side, "T", tick, prov, now, cfg)
    assert t == "LMT" and p == pytest.approx(exp)


@pytest.mark.parametrize(
    "side,bid,ask,maxbps,exp",
    [
        ("BUY", 100, 100.1, 1000, 100.1),
        ("SELL", 99.9, 100, 1000, 99.9),
        ("BUY", 99.9, 101, 5, 100.05),
        ("SELL", 99.9, 100.1, 5, 99.95),
    ],
)
def test_nbbo_maxoffset(side, bid, ask, maxbps, exp):
    now = datetime.now(timezone.utc)
    prov = FakeQuoteProvider({"T": Quote(bid, ask, now)})
    cfg = LimitsConfig(
        buy_offset_frac=1.0,
        sell_offset_frac=1.0,
        max_offset_bps=maxbps,
        wide_spread_bps=100,
        escalate_action="cross",
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, t = calc_limit_price(side, "T", 0.01, prov, now, cfg)
    assert t == "LMT" and p == pytest.approx(exp)


@pytest.mark.parametrize(
    "bid,ask,delta,action,exp,t",
    [
        (99, 101, 0, "cross", 101, "LMT"),
        (99, 101, 0, "market", None, "MKT"),
        (99, 101, 0, "keep", 100.1, "LMT"),
        (99.85, 100.15, 20, "cross", 100.15, "LMT"),
        (99.85, 100.15, 20, "market", None, "MKT"),
        (99.85, 100.15, 20, "keep", 100.1, "LMT"),
    ],
)
def test_wide_or_stale_escalation(bid, ask, delta, action, exp, t):
    ts = datetime.now(timezone.utc) - timedelta(seconds=delta)
    prov = FakeQuoteProvider({"T": Quote(bid, ask, ts)})
    cfg = LimitsConfig(
        buy_offset_frac=0.25,
        sell_offset_frac=0.25,
        max_offset_bps=10,
        wide_spread_bps=50,
        escalate_action=action,
        stale_quote_seconds=10,
        use_ask_bid_cap=True,
    )
    p, ot = calc_limit_price("BUY", "T", 0.01, prov, datetime.now(timezone.utc), cfg)
    assert ot == t
    if exp is None:
        assert p is None
    else:
        assert p == pytest.approx(exp)


@pytest.mark.parametrize("bid,ask", [(100, 100), (101, 100)])
def test_bad_spread(bid, ask):
    now = datetime.now(timezone.utc)
    prov = FakeQuoteProvider({"T": Quote(bid, ask, now)})
    with pytest.raises(ValueError):
        calc_limit_price("BUY", "T", 0.01, prov, now, LimitsConfig())
