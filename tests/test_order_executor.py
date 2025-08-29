from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
import builtins
import pathlib

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
