from datetime import datetime, timezone

from ibkr_etf_rebalancer.config import LimitsConfig
from typing import cast

from ibkr_etf_rebalancer.ibkr_provider import (
    Contract,
    FakeIB,
    IBKRProvider,
    IBKRProviderOptions,
    Order,
    OrderSide,
    OrderType,
)
from ibkr_etf_rebalancer.limit_pricer import calc_limit_price
from ibkr_etf_rebalancer.order_executor import OrderExecutionOptions, execute_orders
from ibkr_etf_rebalancer.pricing import FakeQuoteProvider, Quote


def test_acceptance_flow_fx_sell_buy() -> None:
    now = datetime.now(timezone.utc)

    # Quote setup for limit pricing and fills
    equity_quotes = {
        "GLD": Quote(bid=180.0, ask=180.2, ts=now),
        "GDX": Quote(bid=30.0, ask=30.2, ts=now),
    }
    provider = FakeQuoteProvider(equity_quotes)

    # FakeIB needs FX and equity quotes keyed by contract symbol
    ib_quotes = {
        "USD": Quote(bid=1.34, ask=1.35, ts=now),
        **equity_quotes,
    }
    contracts = {
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
        "GLD": Contract(symbol="GLD"),
        "GDX": Contract(symbol="GDX"),
    }
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True),
        contracts=contracts,
        quotes=ib_quotes,
    )

    cfg = LimitsConfig(wide_spread_bps=0)
    sell_limit, sell_type = calc_limit_price("SELL", "GLD", 0.01, provider, now, cfg)
    buy_limit, buy_type = calc_limit_price("BUY", "GDX", 0.01, provider, now, cfg)

    assert sell_type == "LMT" and sell_limit is not None
    assert buy_type == "LMT" and buy_limit is not None
    # NBBO caps
    assert equity_quotes["GLD"].bid is not None
    assert equity_quotes["GDX"].ask is not None
    assert sell_limit >= equity_quotes["GLD"].bid
    assert buy_limit <= equity_quotes["GDX"].ask

    fx_order = Order(
        contract=contracts["USD"],
        side=OrderSide.BUY,
        quantity=10_000,
        order_type=OrderType.MARKET,
    )
    sell_order = Order(
        contract=contracts["GLD"],
        side=OrderSide.SELL,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=sell_limit,
    )
    buy_order = Order(
        contract=contracts["GDX"],
        side=OrderSide.BUY,
        quantity=100,
        order_type=OrderType.LIMIT,
        limit_price=buy_limit,
    )

    execute_orders(
        cast(IBKRProvider, ib),
        fx_orders=[fx_order],
        sell_orders=[sell_order],
        buy_orders=[buy_order],
        options=OrderExecutionOptions(yes=True),
    )

    events = [
        (e["type"], cast(Order, e["order"]).contract.symbol)
        for e in ib.event_log
        if e["type"] == "placed"
    ]
    assert events == [
        ("placed", "USD"),
        ("placed", "GLD"),
        ("placed", "GDX"),
    ]
