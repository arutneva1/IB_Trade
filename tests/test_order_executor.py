from datetime import datetime, timezone
from typing import cast

from ibkr_etf_rebalancer import pricing
from ibkr_etf_rebalancer.ibkr_provider import (
    Contract,
    FakeIB,
    IBKRProvider,
    IBKRProviderOptions,
    Order,
    Fill,
    OrderSide,
    OrderType,
)
from ibkr_etf_rebalancer.order_executor import execute_orders


def test_execute_orders_sequences_fx_sell_buy() -> None:
    now = datetime.now(timezone.utc)

    contracts = {
        "AAA": Contract(symbol="AAA"),
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    quotes = {
        "AAA": pricing.Quote(bid=99.0, ask=100.0, ts=now, last=99.5),
        "USD": pricing.Quote(bid=1.25, ask=1.26, ts=now, last=1.255),
    }
    opts = IBKRProviderOptions(allow_market_orders=True)
    ib = FakeIB(options=opts, contracts=contracts, quotes=quotes)

    fx_order = Order(
        contract=contracts["USD"],
        side=OrderSide.BUY,
        quantity=1000,
        order_type=OrderType.MARKET,
    )
    sell1 = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=98.0,
    )
    sell2 = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=97.0,
    )
    buy = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=3,
        order_type=OrderType.LIMIT,
        limit_price=101.0,
    )

    fills = execute_orders(
        cast(IBKRProvider, ib),
        fx_orders=[fx_order],
        sell_orders=[sell1, sell2],
        buy_orders=[buy],
    )

    assert [f.contract.symbol for f in fills] == ["USD", "AAA", "AAA", "AAA"]
    assert [f.side for f in fills] == [
        OrderSide.BUY,
        OrderSide.SELL,
        OrderSide.SELL,
        OrderSide.BUY,
    ]

    events = [
        (
            e["type"],
            (
                cast(Order, e["order"]).contract
                if e["type"] == "placed"
                else cast(Fill, e["fill"]).contract
            ).symbol,
            (cast(Order, e["order"]).side if e["type"] == "placed" else cast(Fill, e["fill"]).side),
        )
        for e in ib.event_log
    ]
    assert events == [
        ("placed", "USD", OrderSide.BUY),
        ("filled", "USD", OrderSide.BUY),
        ("placed", "AAA", OrderSide.SELL),
        ("placed", "AAA", OrderSide.SELL),
        ("filled", "AAA", OrderSide.SELL),
        ("filled", "AAA", OrderSide.SELL),
        ("placed", "AAA", OrderSide.BUY),
        ("filled", "AAA", OrderSide.BUY),
    ]
