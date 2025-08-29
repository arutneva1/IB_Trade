from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, cast
import builtins
import pathlib
import logging

import pytest
from freezegun import freeze_time

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
from ibkr_etf_rebalancer.ibkr_provider import ProviderError
from ibkr_etf_rebalancer.order_executor import (
    OrderExecutionOptions,
    OrderExecutionResult,
    execute_orders,
    ExecutionError,
    ConnectionError,
    PacingError,
    ResolutionError,
)


def _basic_contracts(now: datetime) -> tuple[dict[str, Contract], dict[str, pricing.Quote]]:
    contracts = {
        "AAA": Contract(symbol="AAA"),
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    quotes = {
        "AAA": pricing.Quote(bid=99.0, ask=100.0, ts=now, last=99.5),
        "USD": pricing.Quote(bid=1.25, ask=1.26, ts=now, last=1.255),
    }
    return contracts, quotes


def test_execute_orders_dry_run_no_provider_calls() -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(options=IBKRProviderOptions())
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )
    opts = OrderExecutionOptions(dry_run=True, yes=True)
    planned = execute_orders(cast(IBKRProvider, ib), buy_orders=[order], options=opts)
    assert planned == [order]
    assert ib.event_log == []


def test_execute_orders_sequences_fx_sell_buy_event_log() -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
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

    result = cast(
        OrderExecutionResult,
        execute_orders(
            cast(IBKRProvider, ib),
            fx_orders=[fx_order],
            sell_orders=[sell1, sell2],
            buy_orders=[buy],
            options=OrderExecutionOptions(yes=True),
        ),
    )
    fills = result.fills

    assert [f.contract.symbol for f in fills] == ["USD", "AAA", "AAA", "AAA"]
    assert [f.side for f in fills] == [
        OrderSide.BUY,
        OrderSide.SELL,
        OrderSide.SELL,
        OrderSide.BUY,
    ]

    assert result.canceled == []

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


def test_order_logging_details(caplog: pytest.LogCaptureFixture) -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True), contracts=contracts, quotes=quotes
    )

    fill_order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=101.0,
    )
    cancel_order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=50.0,
    )

    with caplog.at_level(logging.INFO):
        execute_orders(
            cast(IBKRProvider, ib),
            buy_orders=[fill_order, cancel_order],
            options=OrderExecutionOptions(yes=True),
        )

    placed = [r for r in caplog.records if r.msg == "order_placed"]
    assert len(placed) == 2
    assert getattr(placed[0], "order_id") == "1"
    assert getattr(placed[0], "symbol") == "AAA"
    assert getattr(placed[0], "side") == "BUY"
    assert getattr(placed[0], "quantity") == 1
    assert getattr(placed[0], "price") == 101.0
    assert getattr(placed[1], "order_id") == "2"
    assert getattr(placed[1], "price") == 50.0

    filled = [r for r in caplog.records if r.msg == "order_filled"]
    assert len(filled) == 1
    assert getattr(filled[0], "order_id") == "1"
    assert getattr(filled[0], "symbol") == "AAA"
    assert getattr(filled[0], "side") == "BUY"
    assert getattr(filled[0], "quantity") == 1
    assert getattr(filled[0], "price") == 100.0

    canceled = [r for r in caplog.records if r.msg == "order_canceled"]
    assert len(canceled) == 1
    assert getattr(canceled[0], "order_id") == "2"
    assert getattr(canceled[0], "symbol") == "AAA"
    assert getattr(canceled[0], "side") == "BUY"
    assert getattr(canceled[0], "quantity") == 1
    assert getattr(canceled[0], "reason") == "unfilled"


def test_execute_orders_concurrency_cap_batches() -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
    pacing: list[int] = []
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True),
        contracts=contracts,
        quotes=quotes,
        concurrency_limit=1,
        pacing_hook=lambda n: pacing.append(n),
    )
    sell1 = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=1,
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
    result = cast(
        OrderExecutionResult,
        execute_orders(
            cast(IBKRProvider, ib),
            sell_orders=[sell1, sell2],
            options=OrderExecutionOptions(concurrency_cap=1, yes=True),
        ),
    )
    fills = result.fills
    assert [f.contract.symbol for f in fills] == ["AAA", "AAA"]
    assert result.canceled == []
    assert pacing == []  # concurrency limit not exceeded
    events = [e["type"] for e in ib.event_log]
    assert events == ["placed", "filled", "placed", "filled"]


def test_execute_orders_provider_concurrency_limit_no_cap() -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
    pacing: list[int] = []
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True),
        contracts=contracts,
        quotes=quotes,
        concurrency_limit=1,
        pacing_hook=lambda n: pacing.append(n),
    )
    orders = [
        Order(
            contract=contracts["AAA"],
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
        )
        for _ in range(3)
    ]
    with pytest.raises(PacingError):
        execute_orders(
            cast(IBKRProvider, ib),
            buy_orders=orders,
            options=OrderExecutionOptions(concurrency_cap=None, yes=True),
        )
    assert pacing == [1]


def test_execute_orders_sequential_buy_orders_pacing() -> None:
    with freeze_time("2024-01-01"):
        now = datetime.now(timezone.utc)
        contracts, quotes = _basic_contracts(now)
        pacing: list[int] = []
        ib = FakeIB(
            options=IBKRProviderOptions(allow_market_orders=True),
            contracts=contracts,
            quotes=quotes,
            concurrency_limit=1,
            pacing_hook=lambda n: pacing.append(n),
        )

        orig_place_order = ib.place_order

        def place_order_with_hook(order: Order) -> str:
            if ib._next_order_id >= 1 and ib._pacing_hook is not None:
                ib._pacing_hook(len(ib._orders) or 1)
            return orig_place_order(order)

        ib.place_order = place_order_with_hook  # type: ignore[method-assign]

        orders = [
            Order(
                contract=contracts["AAA"],
                side=OrderSide.BUY,
                quantity=1,
                order_type=OrderType.MARKET,
            )
            for _ in range(3)
        ]
        result = cast(
            OrderExecutionResult,
            execute_orders(
                cast(IBKRProvider, ib),
                buy_orders=orders,
                options=OrderExecutionOptions(concurrency_cap=1, yes=True),
            ),
        )
        assert [f.order_id for f in result.fills] == ["1", "2", "3"]
        assert len(result.fills) == 3
        assert pacing == [1, 1]


def test_execute_orders_partial_fill_cancels_remaining() -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True), contracts=contracts, quotes=quotes
    )
    sell_ok = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=98.0,
    )
    sell_never = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=120.0,
    )
    result = cast(
        OrderExecutionResult,
        execute_orders(
            cast(IBKRProvider, ib),
            sell_orders=[sell_ok, sell_never],
            options=OrderExecutionOptions(yes=True),
        ),
    )
    assert [f.contract.symbol for f in result.fills] == ["AAA"]
    assert result.canceled == [sell_never]
    assert not result.timed_out
    events = [e["type"] for e in ib.event_log]
    assert events == ["placed", "placed", "filled", "canceled"]


def test_execute_orders_partial_sell_proceeds_scale_buy(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
    quotes["AAA"] = pricing.Quote(bid=10.0, ask=10.0, ts=now, last=10.0)
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True),
        contracts=contracts,
        quotes=quotes,
    )
    sell = Order(
        contract=contracts["AAA"],
        side=OrderSide.SELL,
        quantity=4,
        order_type=OrderType.LIMIT,
        limit_price=10.0,
    )
    buy = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=3,
        order_type=OrderType.LIMIT,
        limit_price=10.0,
    )

    orig_wait = ib.wait_for_fills

    def partial_wait(order_ids: list[str], timeout: float | None = None) -> Sequence[Fill]:
        fills = orig_wait(order_ids, timeout)
        return [
            Fill(
                contract=f.contract,
                side=f.side,
                quantity=(f.quantity / 2 if f.side is OrderSide.SELL else f.quantity),
                price=f.price,
                timestamp=f.timestamp,
                order_id=f.order_id,
            )
            for f in fills
        ]

    monkeypatch.setattr(ib, "wait_for_fills", partial_wait)

    result = cast(
        OrderExecutionResult,
        execute_orders(
            cast(IBKRProvider, ib),
            sell_orders=[sell],
            buy_orders=[buy],
            options=OrderExecutionOptions(yes=True),
            available_cash=0.0,
            max_leverage=1.0,
        ),
    )

    assert result.sell_proceeds == pytest.approx(20.0)
    buy_event = [
        e
        for e in ib.event_log
        if e["type"] == "placed" and cast(Order, e["order"]).side is OrderSide.BUY
    ][0]
    assert cast(Order, buy_event["order"]).quantity == pytest.approx(2.0)


def test_execute_orders_timeout_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True), contracts=contracts, quotes=quotes
    )
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )

    def raise_timeout(order_ids: list[str], timeout: float | None = None) -> list[Fill]:
        raise TimeoutError

    monkeypatch.setattr(ib, "wait_for_fills", raise_timeout)

    result = cast(
        OrderExecutionResult,
        execute_orders(
            cast(IBKRProvider, ib),
            buy_orders=[order],
            options=OrderExecutionOptions(yes=True),
        ),
    )
    assert result.fills == []
    assert result.canceled == [order]
    assert result.timed_out
    events = [e["type"] for e in ib.event_log]
    assert events == ["placed", "canceled"]


def test_execute_orders_retry_skips_previous_fills(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    contracts, quotes = _basic_contracts(now)
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True), contracts=contracts, quotes=quotes
    )

    order1 = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )
    order2 = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=2,
        order_type=OrderType.MARKET,
    )

    opts = OrderExecutionOptions(concurrency_cap=1, yes=True)

    orig_place = ib.place_order
    calls: dict[str, int] = {"n": 0}

    def flaky_place(order: Order) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ProviderError("fail")
        return orig_place(order)

    monkeypatch.setattr(ib, "place_order", flaky_place)

    with pytest.raises(ExecutionError):
        execute_orders(
            cast(IBKRProvider, ib),
            buy_orders=[order1, order2],
            options=opts,
        )

    fills = [cast(Fill, e["fill"]) for e in ib.event_log if e["type"] == "filled"]
    assert len(fills) == 1

    monkeypatch.setattr(ib, "place_order", orig_place)

    execute_orders(
        cast(IBKRProvider, ib),
        buy_orders=[order1, order2],
        options=opts,
        previous_fills=fills,
    )

    placed_qty = [cast(Order, e["order"]).quantity for e in ib.event_log if e["type"] == "placed"]
    filled_qty = [cast(Fill, e["fill"]).quantity for e in ib.event_log if e["type"] == "filled"]
    assert placed_qty == [1, 2]
    assert filled_qty == [1, 2]


def test_execute_orders_kill_switch(tmp_path: pathlib.Path) -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    kill = tmp_path / "kill"
    kill.write_text("")
    ib = FakeIB(options=IBKRProviderOptions(kill_switch=str(kill)), contracts=contracts)
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )
    with pytest.raises(RuntimeError):
        execute_orders(
            cast(IBKRProvider, ib), buy_orders=[order], options=OrderExecutionOptions(yes=True)
        )


def test_execute_orders_paper_only_enforcement() -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(options=IBKRProviderOptions(paper=False, live=False), contracts=contracts)
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )
    with pytest.raises(RuntimeError):
        execute_orders(
            cast(IBKRProvider, ib), buy_orders=[order], options=OrderExecutionOptions(yes=True)
        )


def test_execute_orders_rth_outside_hours() -> None:
    with freeze_time("2024-01-06 12:00:00-05:00"):
        now = datetime.now(timezone.utc)
        contracts, _ = _basic_contracts(now)
        ib = FakeIB(options=IBKRProviderOptions(), contracts=contracts)
        order = Order(
            contract=contracts["AAA"],
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
        )
        with pytest.raises(RuntimeError):
            execute_orders(
                cast(IBKRProvider, ib),
                buy_orders=[order],
                options=OrderExecutionOptions(prefer_rth=True, yes=True),
            )


def test_execute_orders_confirmation_prompt_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(options=IBKRProviderOptions(), contracts=contracts)
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )
    monkeypatch.setattr(builtins, "input", lambda _: "n")
    with pytest.raises(RuntimeError):
        execute_orders(cast(IBKRProvider, ib), buy_orders=[order], options=OrderExecutionOptions())


def test_execute_orders_confirmation_prompt_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(options=IBKRProviderOptions(), contracts=contracts)
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )
    monkeypatch.setattr(builtins, "input", lambda _: "y")
    opts = OrderExecutionOptions(report_only=True)
    result = execute_orders(cast(IBKRProvider, ib), buy_orders=[order], options=opts)
    assert result == [order]


def test_execute_orders_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(options=IBKRProviderOptions(), contracts=contracts)
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )

    def failing_place_order(_order: Order) -> str:
        raise OSError("network")

    monkeypatch.setattr(ib, "place_order", failing_place_order)

    with pytest.raises(ConnectionError) as excinfo:
        execute_orders(
            cast(IBKRProvider, ib), buy_orders=[order], options=OrderExecutionOptions(yes=True)
        )
    assert excinfo.value.exit_code == ConnectionError.exit_code


def test_execute_orders_pacing_error() -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(
        options=IBKRProviderOptions(allow_market_orders=True),
        contracts=contracts,
        concurrency_limit=0,
    )
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )

    with pytest.raises(PacingError) as excinfo:
        execute_orders(
            cast(IBKRProvider, ib), buy_orders=[order], options=OrderExecutionOptions(yes=True)
        )
    assert excinfo.value.exit_code == PacingError.exit_code


def test_execute_orders_resolution_error() -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(options=IBKRProviderOptions(allow_market_orders=True), contracts=contracts)
    order = Order(
        contract=Contract(symbol="ZZZ"),
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )

    with pytest.raises(ResolutionError) as excinfo:
        execute_orders(
            cast(IBKRProvider, ib), buy_orders=[order], options=OrderExecutionOptions(yes=True)
        )
    assert excinfo.value.exit_code == ResolutionError.exit_code


def test_execute_orders_generic_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    contracts, _ = _basic_contracts(now)
    ib = FakeIB(options=IBKRProviderOptions(allow_market_orders=True), contracts=contracts)
    order = Order(
        contract=contracts["AAA"],
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )

    def failing_place_order(_order: Order) -> str:
        raise ProviderError("boom")

    monkeypatch.setattr(ib, "place_order", failing_place_order)

    with pytest.raises(ExecutionError) as excinfo:
        execute_orders(
            cast(IBKRProvider, ib), buy_orders=[order], options=OrderExecutionOptions(yes=True)
        )
    assert excinfo.value.exit_code == ExecutionError.exit_code
