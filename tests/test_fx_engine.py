from datetime import datetime, timedelta, timezone

import pytest

from ibkr_etf_rebalancer.config import FXConfig, PricingConfig
from ibkr_etf_rebalancer.fx_engine import plan_fx_if_needed
from ibkr_etf_rebalancer.rebalance_engine import plan_rebalance_with_fx
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
        funding_cash=20_000,
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
        funding_cash=20_000,
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
        funding_cash=20_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    expected = shortfall * (1 + fx_cfg.fx_buffer_bps / 10_000)
    assert plan.usd_notional == pytest.approx(expected)


def test_missing_fx_quote_skips_plan(fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        funding_cash=5_000,
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
        funding_cash=5_000,
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
        funding_cash=10_000,
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
        funding_cash=10_000,
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
        funding_cash=20_000,
        fx_quote=fresh_quote,
        cfg=cfg,
    )
    assert plan.usd_notional == pytest.approx(5_000)
    assert plan.qty == pytest.approx(5_000)


def test_no_usd_shortfall_skips_plan(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=1_200,
        funding_cash=5_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "no USD shortfall" in plan.reason


def test_no_cad_cash_skips_plan(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        funding_cash=0,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "no CAD cash" in plan.reason


def test_use_ask_when_mid_disabled(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    cfg = fx_cfg.model_copy(update={"use_mid_for_planning": False})
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        funding_cash=5_000,
        fx_quote=fresh_quote,
        cfg=cfg,
    )
    assert fresh_quote.ask is not None
    assert plan.est_rate == pytest.approx(round(fresh_quote.ask, 4))


class DummyProvider:
    def __init__(self, quote: Quote) -> None:
        self.quote = quote

    def get_quote(self, pair: str) -> Quote:  # pragma: no cover - compatibility
        assert pair == "USD.CAD"
        return self.quote

    def get_price(
        self,
        symbol: str,
        price_source: str,
        fallback_to_snapshot: bool = False,
    ) -> float:
        assert symbol == "USD.CAD"
        if price_source == "last" and self.quote.last is not None:
            return self.quote.last
        try:
            return self.quote.mid()
        except ValueError:
            if self.quote.bid is not None:
                return self.quote.bid
            if self.quote.ask is not None:
                return self.quote.ask
            raise


def test_always_top_up_converts(fresh_quote: Quote) -> None:
    cfg = FXConfig(enabled=True, convert_mode="always_top_up")
    provider = DummyProvider(fresh_quote)
    pricing_cfg = PricingConfig()
    _, plan = plan_rebalance_with_fx(
        targets={},
        current={"CASH": 0.0},
        prices={},
        total_equity=1.0,
        fx_cfg=cfg,
        quote_provider=provider,
        pricing_cfg=pricing_cfg,
        funding_cash=20_000,
    )
    assert plan.need_fx is True
    assert plan.usd_notional >= cfg.min_fx_order_usd


def test_prefer_market_hours_blocks_off_hours(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    cfg = fx_cfg.model_copy(update={"prefer_market_hours": True})
    saturday = datetime(2024, 1, 6, tzinfo=timezone.utc)
    plan = plan_fx_if_needed(
        usd_needed=5_000,
        usd_cash=0,
        funding_cash=20_000,
        fx_quote=fresh_quote,
        cfg=cfg,
        now=saturday,
    )
    assert plan.need_fx is False
    assert "outside market hours" in plan.reason
