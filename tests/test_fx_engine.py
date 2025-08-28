from datetime import datetime, timedelta, timezone

import pytest

from ibkr_etf_rebalancer.config import FXConfig
from ibkr_etf_rebalancer.fx_engine import plan_fx_if_needed
from ibkr_etf_rebalancer.pricing import Quote


def _fresh_quote() -> Quote:
    now = datetime.now(timezone.utc)
    return Quote(bid=1.34, ask=1.36, ts=now)


def test_fx_plan_created_with_buffer():
    cfg = FXConfig(enabled=True)
    quote = _fresh_quote()
    plan = plan_fx_if_needed(
        usd_needed=10_000, usd_cash=1_000, cad_cash=20_000, fx_quote=quote, cfg=cfg
    )
    assert plan.need_fx is True
    assert plan.pair == "USD.CAD"
    assert plan.side == "BUY"
    assert plan.order_type == "MKT"
    assert plan.limit_price is None
    # 9000 shortfall * (1 + 20bps) = 9018
    assert plan.usd_notional == pytest.approx(9018.0)
    assert plan.qty == pytest.approx(9018.0)
    assert plan.est_rate == pytest.approx(1.35)


def test_shortfall_below_minimum_skips_fx():
    cfg = FXConfig(enabled=True)
    quote = _fresh_quote()
    plan = plan_fx_if_needed(usd_needed=500, usd_cash=0, cad_cash=20_000, fx_quote=quote, cfg=cfg)
    assert plan.need_fx is False
    assert "below min" in plan.reason


def test_limit_price_calculation():
    cfg = FXConfig(order_type="LMT", limit_slippage_bps=5)
    quote = _fresh_quote()
    plan = plan_fx_if_needed(
        usd_needed=10_000, usd_cash=0, cad_cash=20_000, fx_quote=quote, cfg=cfg
    )
    assert plan.need_fx is True
    assert plan.order_type == "LMT"
    exp_limit = round(1.35 + 1.35 * 0.0005, 4)
    assert plan.limit_price == pytest.approx(exp_limit)


def test_stale_quote_returns_no_plan():
    cfg = FXConfig()
    old = datetime.now(timezone.utc) - timedelta(seconds=11)
    quote = Quote(bid=1.34, ask=1.36, ts=old)
    plan = plan_fx_if_needed(
        usd_needed=10_000, usd_cash=0, cad_cash=20_000, fx_quote=quote, cfg=cfg
    )
    assert plan.need_fx is False
    assert "stale" in plan.reason
