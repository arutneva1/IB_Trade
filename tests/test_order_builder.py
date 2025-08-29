"""Tests for :mod:`order_builder`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ibkr_etf_rebalancer.config import LimitsConfig
from ibkr_etf_rebalancer.fx_engine import FxPlan
from ibkr_etf_rebalancer.ibkr_provider import Contract, OrderSide, OrderType
from ibkr_etf_rebalancer.order_builder import build_equity_orders, build_fx_order
from ibkr_etf_rebalancer.pricing import FakeQuoteProvider, Quote


@dataclass(frozen=True)
class ContractWithTick(Contract):
    min_tick: float = 0.01


def test_buy_vs_sell_mapping() -> None:
    """Positive quantities map to BUY and negative to SELL."""

    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider(
        {
            "AAA": Quote(bid=99.9, ask=100.1, ts=now),
            "BBB": Quote(bid=49.9, ask=50.1, ts=now),
        }
    )
    quotes = {sym: provider.get_quote(sym) for sym in ("AAA", "BBB")}
    contracts = {
        "AAA": ContractWithTick(symbol="AAA", min_tick=0.05),
        "BBB": ContractWithTick(symbol="BBB", min_tick=0.05),
    }
    plan = {"AAA": 10, "BBB": -5}
    cfg = SimpleNamespace(order_type="LMT", limits=LimitsConfig())

    orders = build_equity_orders(plan, quotes, cfg, contracts, allow_fractional=True)
    by_symbol = {o.contract.symbol: o for o in orders}

    assert by_symbol["AAA"].side is OrderSide.BUY
    assert by_symbol["BBB"].side is OrderSide.SELL


def test_fx_order_creation() -> None:
    """FX plans are turned into rounded FX orders."""

    fx_plan = FxPlan(
        need_fx=True,
        pair="USD.CAD",
        side="BUY",
        usd_notional=1000.0,
        est_rate=1.25057,
        qty=1000.123,
        order_type="LMT",
        limit_price=1.25057,
        route="IDEALPRO",
        wait_for_fill_seconds=0,
        reason="test",
    )
    contract = ContractWithTick(
        symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO", min_tick=0.0001
    )

    order = build_fx_order(fx_plan, contract)
    assert order.side is OrderSide.BUY
    assert order.order_type is OrderType.LIMIT
    assert order.quantity == pytest.approx(1000.12, rel=1e-6)
    assert order.limit_price == pytest.approx(1.2506, rel=1e-6)


def test_order_type_switch_between_lmt_and_mkt() -> None:
    """Orders honour the requested ``order_type``."""

    now = datetime.now(timezone.utc)
    quotes = {"AAA": Quote(bid=99.0, ask=101.0, ts=now)}
    contracts = {"AAA": Contract(symbol="AAA")}
    plan = {"AAA": 10}
    cfg = SimpleNamespace(order_type="MKT", limits=LimitsConfig())

    orders = build_equity_orders(plan, quotes, cfg, contracts, allow_fractional=True)
    order = orders[0]
    assert order.order_type is OrderType.MARKET
    assert order.limit_price is None


def test_escalation_to_market_on_limit_instruction() -> None:
    """Wide markets escalate limit orders to market orders."""

    now = datetime.now(timezone.utc)
    quotes = {"AAA": Quote(bid=100.0, ask=101.0, ts=now)}
    contracts = {"AAA": Contract(symbol="AAA")}
    limits = LimitsConfig(escalate_action="market", wide_spread_bps=1)
    cfg = SimpleNamespace(order_type="LMT", limits=limits)
    plan = {"AAA": 10}

    orders = build_equity_orders(plan, quotes, cfg, contracts, allow_fractional=True)
    order = orders[0]
    assert order.order_type is OrderType.MARKET
    assert order.limit_price is None


def test_limit_prices_capped_at_nbbo() -> None:
    """Limit prices never cross the current NBBO."""

    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"AAA": Quote(bid=100.0, ask=100.2, ts=now)})
    quotes = {"AAA": provider.get_quote("AAA")}
    contracts = {"AAA": ContractWithTick(symbol="AAA", min_tick=0.05)}
    plan = {"AAA": 10}
    cfg = SimpleNamespace(order_type="LMT", limits=LimitsConfig())

    orders = build_equity_orders(plan, quotes, cfg, contracts, allow_fractional=True)
    order = orders[0]
    assert order.limit_price is not None
    limit_price = order.limit_price
    ask = quotes["AAA"].ask
    assert ask is not None
    assert limit_price <= ask
    # tick rounding honoured
    assert abs(limit_price / 0.05 - float(round(limit_price / 0.05))) < 1e-9


def test_fractional_rounding_when_disallowed() -> None:
    """Quantities are rounded to whole shares when fractional trading is off."""

    now = datetime.now(timezone.utc)
    quotes = {
        "AAA": Quote(bid=10.0, ask=10.0, ts=now),
        "BBB": Quote(bid=20.0, ask=20.0, ts=now),
        "CCC": Quote(bid=30.0, ask=30.0, ts=now),
    }
    contracts = {sym: Contract(symbol=sym) for sym in quotes}
    # Two small orders that should round to zero and be dropped and two that
    # should round to one share each (buy and sell).
    plan = {"AAA": 0.6, "BBB": 0.4, "CCC": -0.6, "DDD": -0.4}
    contracts["DDD"] = Contract(symbol="DDD")
    quotes["DDD"] = Quote(bid=40.0, ask=40.0, ts=now)
    cfg = SimpleNamespace(order_type="MKT")

    orders = build_equity_orders(plan, quotes, cfg, contracts, allow_fractional=False)
    by_symbol = {o.contract.symbol: o for o in orders}

    assert by_symbol["AAA"].quantity == 1
    assert by_symbol["AAA"].side is OrderSide.BUY
    assert by_symbol["CCC"].quantity == 1
    assert by_symbol["CCC"].side is OrderSide.SELL
    assert "BBB" not in by_symbol
    assert "DDD" not in by_symbol
