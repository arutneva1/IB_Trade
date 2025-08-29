import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ibkr_etf_rebalancer.config import FXConfig, PricingConfig
from ibkr_etf_rebalancer.pricing import FakeQuoteProvider, Quote
from ibkr_etf_rebalancer.rebalance_engine import generate_orders, plan_rebalance_with_fx

# Ensure package root on path when running tests directly
sys.path.append(str(Path(__file__).resolve().parents[1]))


PRICES = {"AAA": 100.0, "BBB": 100.0}
EQUITY = 100_000.0


def test_no_trade_when_within_band():
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.05,
        min_order=500.0,
        max_leverage=1.5,
    )
    assert plan.orders == {}


def test_overweight_positions_generate_sells():
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    current = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert plan.orders["AAA"] == -100


def test_underweight_positions_generate_buys():
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert plan.orders["AAA"] == 100


def test_min_order_filtering():
    targets = {"AAA": 0.503, "BBB": 0.497, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=500.0,
        max_leverage=1.5,
    )
    assert plan.orders == {}


def test_min_order_dropped_reason_recorded():
    targets = {"AAA": 0.503, "BBB": 0.497, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=500.0,
        max_leverage=1.5,
    )
    assert plan.orders == {}
    assert plan.dropped == {
        "AAA": "notional 300.00 below min_order 500.00",
        "BBB": "notional 300.00 below min_order 500.00",
    }


def test_scaled_buy_dropped_below_min_order():
    targets = {"AAA": 0.006, "CASH": 0.0}
    current = {"AAA": 0.0, "CASH": 0.012}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=500.0,
        max_leverage=1.5,
        cash_buffer_pct=0.8,  # 0.8% buffer
    )
    assert plan.orders == {}


def test_scaled_buy_dropped_below_min_order_due_to_leverage():
    targets = {"AAA": 1.006, "CASH": -0.006}
    current = {"AAA": 1.0, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=500.0,
        max_leverage=1.0,
    )
    assert plan.orders == {}


def test_margin_leverage_scaling():
    targets = {"AAA": 1.3, "BBB": 0.3, "CASH": -0.6}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert plan.orders["AAA"] == 700
    assert plan.orders["BBB"] == -200


def test_fractional_buy_rounds_up():
    targets = {"AAA": 0.0012}
    current = {"AAA": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert plan.orders["AAA"] == 2


def test_fractional_sell_rounds_away_from_zero():
    targets = {"AAA": 0.0010}
    current = {"AAA": 0.0022}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert plan.orders["AAA"] == -2


def test_sell_rounding_drops_order_when_less_than_one_share():
    targets = {"AAA": 0.0}
    current = {"AAA": 0.0004}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert plan.orders == {}


def test_sell_rounding_capped_at_available_shares():
    targets = {"AAA": 0.0003}
    current = {"AAA": 0.0014}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
    )
    assert plan.orders["AAA"] == -1


def test_cash_buffer_limits_buys():
    targets = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        cash_buffer_pct=5.0,  # 5% buffer
        allow_fractional=False,
    )
    assert plan.orders["BBB"] == -100
    assert plan.orders["AAA"] == 50


def test_maintenance_buffer_limits_leverage():
    targets = {"AAA": 1.3, "BBB": 0.3, "CASH": -0.6}
    current = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
        maintenance_buffer_pct=10.0,
        allow_fractional=False,
    )
    assert plan.orders["BBB"] == -200
    assert plan.orders["AAA"] == 600


@pytest.mark.parametrize(
    "current,expected",
    [
        ({"AAA": 0.51, "BBB": 0.49, "CASH": 0.0}, {"AAA": -10, "BBB": 10}),
        ({"AAA": 0.49, "BBB": 0.51, "CASH": 0.0}, {"AAA": 10, "BBB": -10}),
        ({"AAA": 0.505, "BBB": 0.495, "CASH": 0.0}, {}),
    ],
)
def test_total_drift_trigger_mixed_sign(current, expected):
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    plan = generate_orders(
        targets,
        current,
        PRICES,
        EQUITY,
        bands=0.02,
        min_order=0.0,
        max_leverage=1.5,
        allow_fractional=False,
        trigger_mode="total_drift",
        portfolio_total_band_bps=100,
    )
    assert plan.orders == expected


def test_fx_top_up_generates_plan_and_feasible_orders():
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    current = {"AAA": 0.0, "BBB": 0.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    fx_cfg = FXConfig(enabled=True)
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"USD.CAD": Quote(1.25, 1.26, now)})
    pricing_cfg = PricingConfig()

    plan, fx_plan = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=pricing_cfg,
        funding_cash=150_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )

    assert fx_plan.need_fx is True
    buy_notional = sum(
        shares * prices[symbol] for symbol, shares in plan.orders.items() if shares > 0
    )
    usd_cash_after = current.get("CASH", 0.0) * EQUITY + fx_plan.usd_notional
    assert buy_notional <= usd_cash_after + 1e-6
    assert plan.orders["AAA"] == pytest.approx(500)
    assert plan.orders["BBB"] == pytest.approx(500)


def test_sells_partially_fund_buys_reducing_fx():
    targets = {"AAA": 0.55, "BBB": 0.55}
    current = {"AAA": 0.6, "BBB": 0.4, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    fx_cfg = FXConfig(enabled=True)
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"USD.CAD": Quote(1.25, 1.26, now)})
    pricing_cfg = PricingConfig()

    plan, fx_plan = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=pricing_cfg,
        funding_cash=10_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )

    est_rate = round(provider.get_quote("USD.CAD").mid(), 4)
    expected_fx = round(10_000 / est_rate, 2)
    assert fx_plan.need_fx is True
    assert fx_plan.usd_notional == pytest.approx(expected_fx)
    assert plan.orders["AAA"] == pytest.approx(-50)
    assert plan.orders["BBB"] == pytest.approx(150)


def test_fx_limit_price_honours_spread():
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    current = {"AAA": 0.0, "BBB": 0.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    now = datetime.now(timezone.utc)
    quote = Quote(1.25, 1.2502, now)
    provider = FakeQuoteProvider({"USD.CAD": quote})
    fx_cfg = FXConfig(enabled=True, order_type="LMT", limit_slippage_bps=5)
    pricing_cfg = PricingConfig()

    _, fx_plan = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=pricing_cfg,
        funding_cash=150_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )

    assert fx_plan.need_fx is True
    assert fx_plan.limit_price is not None
    assert fx_plan.limit_price >= quote.ask


def test_unsupported_funding_currency_rejected():
    targets = {"AAA": 0.5, "BBB": 0.5}
    current = {"AAA": 0.0, "BBB": 0.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    fx_cfg = FXConfig(enabled=True)
    pricing_cfg = PricingConfig()
    provider = FakeQuoteProvider({})

    with pytest.raises(ValueError):
        plan_rebalance_with_fx(
            targets,
            current,
            prices,
            EQUITY,
            fx_cfg=fx_cfg,
            quote_provider=provider,
            pricing_cfg=pricing_cfg,
            funding_currency="EUR",
            funding_cash=10_000.0,
        )


def test_mixed_case_funding_currency_accepted():
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    current = {"AAA": 0.0, "BBB": 0.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    fx_cfg = FXConfig(enabled=True)
    pricing_cfg = PricingConfig()
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"USD.CAD": Quote(1.25, 1.26, now)})

    _, fx_plan = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=pricing_cfg,
        funding_currency="cAd",
        funding_cash=150_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )

    assert fx_plan.pair == "USD.CAD"
    assert fx_plan.need_fx is True


def test_fx_snapshot_fallback():
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    current = {"AAA": 0.0, "BBB": 0.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    fx_cfg = FXConfig(enabled=True)
    pricing_cfg = PricingConfig(fallback_to_snapshot=True)
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"USD.CAD": Quote(None, None, now)}, snapshots={"USD.CAD": 1.2})

    _, fx_plan = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=pricing_cfg,
        funding_cash=150_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )

    assert fx_plan.need_fx is True
    assert fx_plan.est_rate == pytest.approx(1.2)


def test_fx_price_source_precedence():
    targets = {"AAA": 0.5, "BBB": 0.5, "CASH": 0.0}
    current = {"AAA": 0.0, "BBB": 0.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    now = datetime.now(timezone.utc)
    quote = Quote(1.2, 1.3, now, last=1.1)
    provider = FakeQuoteProvider({"USD.CAD": quote})
    fx_cfg = FXConfig(enabled=True)

    cfg_last = PricingConfig(price_source="last")
    _, plan_last = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=cfg_last,
        funding_cash=150_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )
    assert plan_last.est_rate == pytest.approx(1.1)

    cfg_mid = PricingConfig(price_source="midpoint")
    _, plan_mid = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=cfg_mid,
        funding_cash=150_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )
    assert plan_mid.est_rate == pytest.approx((quote.bid + quote.ask) / 2)

    cfg_bid = PricingConfig(price_source="bidask")
    _, plan_bid = plan_rebalance_with_fx(
        targets,
        current,
        prices,
        EQUITY,
        fx_cfg=fx_cfg,
        quote_provider=provider,
        pricing_cfg=cfg_bid,
        funding_cash=150_000.0,
        bands=0.0,
        min_order=0.0,
        max_leverage=1.5,
    )
    assert plan_bid.est_rate == pytest.approx(quote.bid)


def test_invalid_trigger_mode():
    targets = {"AAA": 0.5}
    current = {"AAA": 0.5}
    with pytest.raises(ValueError):
        generate_orders(
            targets,
            current,
            PRICES,
            EQUITY,
            trigger_mode="invalid",
        )
