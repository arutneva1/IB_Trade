import pathlib

import pytest
from datetime import datetime, timedelta, timezone
from typing import cast

from ibkr_etf_rebalancer import pricing
from ibkr_etf_rebalancer.ibkr_provider import (
    AccountValue,
    Contract,
    FakeIB,
    IBKRProviderOptions,
    Position,
    Order,
    OrderSide,
    OrderType,
    PacingError,
    ResolutionError,
)


@pytest.fixture
def sample_account_values() -> list[AccountValue]:
    return [AccountValue(tag="NetLiquidation", value=1000.0, currency="USD")]


@pytest.fixture
def sample_positions() -> list[Position]:
    contract = Contract(symbol="AAA")
    return [Position(account="DU123", contract=contract, quantity=5, avg_price=100.0)]


@pytest.fixture
def seeded_ib(
    sample_account_values: list[AccountValue], sample_positions: list[Position]
) -> FakeIB:
    return FakeIB(account_values=sample_account_values, positions=sample_positions)


def test_get_account_values_returns_copy(
    seeded_ib: FakeIB, sample_account_values: list[AccountValue]
) -> None:
    values = cast(list[AccountValue], seeded_ib.get_account_values())
    assert values == sample_account_values
    assert values is not seeded_ib.state["account_values"]
    values.pop()
    assert seeded_ib.get_account_values() == sample_account_values


def test_get_positions_returns_copy(seeded_ib: FakeIB, sample_positions: list[Position]) -> None:
    positions = cast(list[Position], seeded_ib.get_positions())
    assert positions == sample_positions
    assert positions is not seeded_ib.state["positions"]
    positions.pop()
    assert seeded_ib.get_positions() == sample_positions


def test_connect_disconnect_idempotent_state() -> None:
    ib = FakeIB()
    ib.connect()
    ib.connect()
    assert ib.state["connected"] is True
    ib.disconnect()
    ib.disconnect()
    assert ib.state["connected"] is False


def test_resolve_contract_with_symbol_overrides() -> None:
    contracts = {
        "AAA": Contract(symbol="AAA"),
        "BBB": Contract(symbol="BBB"),
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    overrides: dict[str, str | Contract] = {
        "BBB": "AAA",  # string override
        "FX": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    ib = FakeIB(contracts=contracts, symbol_overrides=overrides)

    assert ib.resolve_contract(Contract(symbol="AAA")) == contracts["AAA"]
    # BBB is overridden to AAA symbol
    assert ib.resolve_contract(Contract(symbol="BBB")) == contracts["AAA"]
    # FX is overridden to the provided Contract instance
    assert ib.resolve_contract(Contract(symbol="FX")) == overrides["FX"]


def test_resolve_contract_unmapped_symbol_raises() -> None:
    ib = FakeIB(contracts={"AAA": Contract(symbol="AAA")})
    with pytest.raises(ResolutionError):
        ib.resolve_contract(Contract(symbol="ZZZ"))


def test_get_quote_fresh_stale_bid_only_ask_only() -> None:
    now = datetime.now(timezone.utc)
    past_naive = datetime.utcnow() - timedelta(hours=1)
    contracts = {
        "AAA": Contract("AAA"),
        "OLD": Contract("OLD"),
        "BID": Contract("BID"),
        "ASK": Contract("ASK"),
    }
    quotes = {
        "AAA": pricing.Quote(bid=100.0, ask=101.0, ts=now),
        "OLD": pricing.Quote(bid=10.0, ask=11.0, ts=past_naive),
        "BID": pricing.Quote(bid=99.0, ask=None, ts=now),
        "ASK": pricing.Quote(bid=None, ask=1.5, ts=now),
    }
    ib = FakeIB(contracts=contracts, quotes=quotes)

    # fresh quote
    q = cast(pricing.Quote, ib.get_quote(contracts["AAA"]))
    assert q.bid == pytest.approx(100.0)
    assert q.ask == pytest.approx(101.0)
    assert q.ts.tzinfo is timezone.utc

    # stale quote with naive timestamp becomes UTC-aware
    q = cast(pricing.Quote, ib.get_quote(contracts["OLD"]))
    assert q.ts == past_naive.replace(tzinfo=timezone.utc)

    # bid-only
    q = cast(pricing.Quote, ib.get_quote(contracts["BID"]))
    assert q.bid == pytest.approx(99.0)
    assert q.ask is None

    # ask-only
    q = cast(pricing.Quote, ib.get_quote(contracts["ASK"]))
    assert q.ask == pytest.approx(1.5)
    assert q.bid is None


def test_order_lifecycle_and_fills() -> None:
    now = datetime.now(timezone.utc)
    contracts = {
        "AAA": Contract(symbol="AAA"),
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    quotes = {
        "AAA": pricing.Quote(bid=99.0, ask=100.0, ts=now, last=99.5),
        "USD": pricing.Quote(bid=1.25, ask=1.26, ts=now, last=1.255),
    }
    options = IBKRProviderOptions(allow_market_orders=True)
    ib = FakeIB(options=options, contracts=contracts, quotes=quotes)

    # BUY limit that remains open (limit below ask)
    buy_open = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=99.0,
    )
    buy_open_id = ib.place_order(buy_open)

    # SELL limit that fills (limit below market bid)
    sell_fill = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=98.0,
    )
    sell_fill_id = ib.place_order(sell_fill)

    # FX market BUY
    fx_mkt = Order(
        contract=contracts["USD"],
        side=OrderSide.BUY,
        quantity=1000,
        order_type=OrderType.MARKET,
    )
    fx_mkt_id = ib.place_order(fx_mkt)

    # Equity market SELL
    sell_mkt = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=2,
        order_type=OrderType.MARKET,
    )
    sell_mkt_id = ib.place_order(sell_mkt)

    fills = ib.wait_for_fills([sell_fill_id, fx_mkt_id, sell_mkt_id, buy_open_id])
    assert [f.side for f in fills] == [OrderSide.SELL, OrderSide.BUY, OrderSide.SELL]

    prices = [f.price for f in fills]
    assert prices[0] == pytest.approx(99.0)
    assert prices[1] == pytest.approx(1.26)
    assert prices[2] == pytest.approx(99.0)

    ts = [cast(datetime, f.timestamp) for f in fills]
    assert ts == sorted(ts)
    for earlier, later in zip(ts, ts[1:]):
        assert earlier < later

    # open order remains until canceled
    assert buy_open_id in ib._orders
    ib.cancel(buy_open_id)
    assert buy_open_id not in ib._orders

    events = ib.event_log
    assert [(e["type"], e["order_id"]) for e in events] == [
        ("placed", buy_open_id),
        ("placed", sell_fill_id),
        ("placed", fx_mkt_id),
        ("placed", sell_mkt_id),
        ("filled", sell_fill_id),
        ("filled", fx_mkt_id),
        ("filled", sell_mkt_id),
        ("canceled", buy_open_id),
    ]


def test_pacing_limit_triggers_backoff_hook() -> None:
    contract = Contract(symbol="AAA")
    quote = pricing.Quote(bid=99.0, ask=100.0, ts=datetime.now(timezone.utc))
    called: list[int] = []

    def hook(n: int) -> None:
        called.append(n)

    ib = FakeIB(
        contracts={"AAA": contract},
        quotes={"AAA": quote},
        concurrency_limit=1,
        pacing_hook=hook,
    )

    order = Order(
        contract=contract,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=100.0,
    )
    ib.place_order(order)
    with pytest.raises(PacingError):
        ib.place_order(order)
    assert called == [1]


def test_market_orders_rejected_by_default() -> None:
    contract = Contract(symbol="AAA")
    ib = FakeIB(contracts={"AAA": contract})
    order = Order(contract=contract, side=OrderSide.BUY, quantity=1, order_type=OrderType.MARKET)
    with pytest.raises(RuntimeError):
        ib.place_order(order)


def test_market_orders_allowed_when_enabled() -> None:
    contract = Contract(symbol="AAA")
    options = IBKRProviderOptions(allow_market_orders=True)
    ib = FakeIB(options=options, contracts={"AAA": contract})
    order = Order(contract=contract, side=OrderSide.BUY, quantity=1, order_type=OrderType.MARKET)
    order_id = ib.place_order(order)
    assert order_id in ib._orders


def test_place_order_abort_on_kill_switch(tmp_path: pathlib.Path) -> None:
    contract = Contract(symbol="AAA")
    kill_file = tmp_path / "STOP"
    kill_file.write_text("halt")

    options = IBKRProviderOptions(paper=True, kill_switch=str(kill_file))
    ib = FakeIB(options=options, contracts={"AAA": contract})

    order = Order(contract=contract, side=OrderSide.BUY, quantity=1, order_type=OrderType.MARKET)
    with pytest.raises(RuntimeError):
        ib.place_order(order)


def test_place_order_abort_when_live_disallowed() -> None:
    contract = Contract(symbol="AAA")
    options = IBKRProviderOptions(paper=False, live=True)
    ib = FakeIB(options=options, contracts={"AAA": contract})

    order = Order(contract=contract, side=OrderSide.BUY, quantity=1, order_type=OrderType.MARKET)
    with pytest.raises(RuntimeError):
        ib.place_order(order)
