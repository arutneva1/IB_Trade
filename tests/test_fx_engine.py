from datetime import datetime, timedelta, timezone, date

import pytest

from ibkr_etf_rebalancer.config import FXConfig, PricingConfig
from ibkr_etf_rebalancer.fx_engine import plan_fx_if_needed, _is_fx_market_open
from ibkr_etf_rebalancer.rebalance_engine import plan_rebalance_with_fx
from ibkr_etf_rebalancer.pricing import Quote
from ibkr_etf_rebalancer.util import from_bps


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
    expected = shortfall * (1 + from_bps(fx_cfg.fx_buffer_bps))
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
    now = fresh_quote.ts + timedelta(seconds=fx_cfg.stale_quote_seconds + 1)
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        funding_cash=5_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
        now=now,
    )
    assert plan.need_fx is False
    assert "stale" in plan.reason


def test_fx_quote_at_threshold_trades(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    now = fresh_quote.ts + timedelta(seconds=fx_cfg.stale_quote_seconds)
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        funding_cash=5_000,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
        now=now,
    )
    assert plan.need_fx is True
    assert "stale" not in plan.reason


@pytest.mark.parametrize(
    "bid, ask",
    [
        (None, 1.23456),
        (1.23456, None),
    ],
    ids=["missing_bid", "missing_ask"],
)
def test_incomplete_fx_quote_skips_plan(
    bid: float | None, ask: float | None, fx_cfg: FXConfig
) -> None:
    quote = Quote(bid=bid, ask=ask, ts=datetime.now(timezone.utc))
    plan = plan_fx_if_needed(
        usd_needed=1_000,
        usd_cash=0,
        funding_cash=5_000,
        fx_quote=quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert plan.reason == "incomplete FX quote"


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
    expected = round(1_234.56 * (1 + from_bps(fx_cfg.fx_buffer_bps)), 2)
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
    assert plan.limit_price is not None
    assert quote.ask is not None
    assert plan.limit_price >= quote.ask
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


def test_funding_cash_caps_order(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=5_000,
        usd_cash=0,
        funding_cash=1_500,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    est_rate = round(fresh_quote.mid(), 4)
    expected = round(1_500 / est_rate, 2)
    assert plan.need_fx is True
    assert plan.usd_notional == pytest.approx(expected)
    assert plan.qty == pytest.approx(expected)


def test_insufficient_funding_cash_skips(fresh_quote: Quote, fx_cfg: FXConfig) -> None:
    plan = plan_fx_if_needed(
        usd_needed=5_000,
        usd_cash=0,
        funding_cash=500,
        fx_quote=fresh_quote,
        cfg=fx_cfg,
    )
    assert plan.need_fx is False
    assert "insufficient CAD" in plan.reason


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


def test_prefer_market_hours_blocks_after_friday_close(
    fresh_quote: Quote, fx_cfg: FXConfig
) -> None:
    cfg = fx_cfg.model_copy(update={"prefer_market_hours": True})
    # Friday after the 22:00 UTC close
    friday = datetime(2024, 1, 5, 22, 30, tzinfo=timezone.utc)
    plan = plan_fx_if_needed(
        usd_needed=5_000,
        usd_cash=0,
        funding_cash=20_000,
        fx_quote=fresh_quote,
        cfg=cfg,
        now=friday,
    )
    assert plan.need_fx is False
    assert "outside market hours" in plan.reason


def test_prefer_market_hours_blocks_before_sunday_open(
    fresh_quote: Quote, fx_cfg: FXConfig
) -> None:
    cfg = fx_cfg.model_copy(update={"prefer_market_hours": True})
    # Sunday before the 22:00 UTC open
    sunday = datetime(2024, 1, 7, 21, 30, tzinfo=timezone.utc)
    plan = plan_fx_if_needed(
        usd_needed=5_000,
        usd_cash=0,
        funding_cash=20_000,
        fx_quote=fresh_quote,
        cfg=cfg,
        now=sunday,
    )
    assert plan.need_fx is False
    assert "outside market hours" in plan.reason


def test_is_fx_market_open_handles_dst_boundary() -> None:
    # July is in daylight saving time for New York. Market opens at 21:00 UTC.
    before_open = datetime(2024, 7, 7, 20, 59, tzinfo=timezone.utc)
    after_open = datetime(2024, 7, 7, 21, 1, tzinfo=timezone.utc)
    assert _is_fx_market_open(before_open) is False
    assert _is_fx_market_open(after_open) is True


def test_is_fx_market_open_blocks_holidays() -> None:
    holiday = date(2024, 1, 1)
    ts = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    assert _is_fx_market_open(ts, holidays=[holiday]) is False
    ts_next = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    assert _is_fx_market_open(ts_next, holidays=[holiday]) is True


def test_prefer_market_hours_blocks_holiday(
    fresh_quote: Quote, fx_cfg: FXConfig
) -> None:
    cfg = fx_cfg.model_copy(
        update={"prefer_market_hours": True, "market_holidays": [date(2024, 1, 1)]}
    )
    new_year = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    plan = plan_fx_if_needed(
        usd_needed=5_000,
        usd_cash=0,
        funding_cash=20_000,
        fx_quote=fresh_quote,
        cfg=cfg,
        now=new_year,
    )
    assert plan.need_fx is False
    assert "outside market hours" in plan.reason
