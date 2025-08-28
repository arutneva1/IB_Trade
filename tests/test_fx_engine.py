from datetime import datetime, timedelta, timezone

import pytest

from ibkr_etf_rebalancer.config import FXConfig
from ibkr_etf_rebalancer.fx_engine import plan_fx_if_needed
from ibkr_etf_rebalancer.pricing import Quote


@pytest.fixture
def fresh_quote() -> Quote:
    now = datetime.now(timezone.utc)
    return Quote(bid=1.23456, ask=1.23476, ts=now)


@pytest.fixture
def fx_cfg() -> FXConfig:
    return FXConfig(enabled=True)


def test_cad_only_cash_needs_fx(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=5_000,
        usd_cash=0,
        cad_cash=20_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is True
    assert plan.pair == "USD.CAD"
    assert plan.side == "BUY"
    assert plan.order_type == "MKT"


def test_shortfall_below_min_skips_fx(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=500,
        usd_cash=0,
        cad_cash=20_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "below min" in plan.reason


def test_buffer_applied_to_notional(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    shortfall = 2_000
    plan = plan_fx_if_needed(
        usd_needed=shortfall,
        usd_cash=0,
        cad_cash=20_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    expected = shortfall * (1 + fx_cfg.fx_buffer_bps / 10_000)
    assert plan.usd_notional == pytest.approx(expected)


def test_missing_fx_quote_skips_plan(fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        cad_cash=5_000,
        fx_quote=None,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "no FX quote" in plan.reason


def test_stale_fx_quote_skips_plan(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    old_ts = fresh_quote.ts - timedelta(seconds=11)
    stale = Quote(bid=fresh_quote.bid, ask=fresh_quote.ask, ts=old_ts)
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        cad_cash=5_000,
        fx_quote=stale,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "stale" in plan.reason


def test_market_rounding(fx_cfg: FXConfig) -> None:
    quote = Quote(bid=1.23451, ask=1.23491, ts=datetime.now(timezone.utc))
    plan = plan_fx_if_needed(
        usd_needed=1_234.56,
        usd_cash=0,
        cad_cash=10_000,
        fx_quote=quote,
        cfg=fx_cfg,
    )
    assert plan.est_rate == pytest.approx(1.2347)
    expected = round(1_234.56 * (1 + fx_cfg.fx_buffer_bps / 10_000), 2)
    assert plan.usd_notional == pytest.approx(expected)
    assert plan.qty == pytest.approx(expected)


def test_limit_order_rounding(fx_cfg: FXConfig) -> None:
    quote = Quote(bid=1.23456, ask=1.23476, ts=datetime.now(timezone.utc))
    cfg = fx_cfg.model_copy(update={"order_type": "LMT", "limit_slippage_bps": 5})
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        cad_cash=10_000,
        fx_quote=quote,
        cfg=cfg,
    )
    assert plan.limit_price == pytest.approx(1.2353)
    assert plan.order_type == "LMT"


def test_max_order_cap_applied(fresh_quote: Quote) -> None:
    cfg = FXConfig(enabled=True, max_fx_order_usd=5_000)
    plan = plan_fx_if_needed(
        usd_needed=10_000,
        usd_cash=100,
        cad_cash=20_000,
        fx_quote=fresh_quote,
        cfg=cfg,
    )
    assert plan.usd_notional == pytest.approx(5_000)
    assert plan.qty == pytest.approx(5_000)


def test_no_usd_shortfall_skips_plan(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=1_200,
        cad_cash=5_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "no USD shortfall" in plan.reason


def test_no_cad_cash_skips_plan(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        cad_cash=0,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "no CAD cash" in plan.reason
