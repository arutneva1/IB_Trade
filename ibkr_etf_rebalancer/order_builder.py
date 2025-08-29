"""Order construction helpers.

This module translates high level rebalance plans into concrete broker
``Order`` objects.  The functions are intentionally lightweight: they perform
basic validation, apply limit prices when requested and ensure prices respect
contract tick sizes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Mapping

from . import limit_pricer
from .config import LimitsConfig, RebalanceConfig
from .fx_engine import FxPlan
from .ibkr_provider import Contract, Order, OrderSide, OrderType, RTH
from .pricing import Quote

__all__ = ["build_equity_orders", "build_fx_order"]


def _min_tick(contract: Contract) -> float:
    """Return the contract's minimum tick if available."""

    tick = getattr(contract, "min_tick", 0.01)
    try:
        tick = float(tick)
    except Exception:  # pragma: no cover - defensive
        tick = 0.01
    if tick <= 0:  # pragma: no cover - defensive
        tick = 0.01
    return tick


def build_equity_orders(
    plan: Mapping[str, float],
    quotes: Mapping[str, Quote],
    cfg: RebalanceConfig | SimpleNamespace,
    contracts: Mapping[str, Contract],
    allow_fractional: bool,
    prefer_rth: bool = True,
) -> list[Order]:
    """Return ``Order`` objects for an equity rebalance *plan*.

    ``plan`` maps symbols to share deltas (positive for buys, negative for
    sells).  ``quotes`` provides current market quotes used for limit pricing
    while ``contracts`` supplies the corresponding broker contract objects.
    ``allow_fractional`` controls whether quantities may include fractional
    shares.  The ``cfg`` object must provide ``order_type`` and may optionally
    supply a ``limits`` attribute containing a :class:`LimitsConfig` instance.
    When ``cfg.order_type`` is ``"LMT"`` the :mod:`limit_pricer` helpers are used
    to calculate conservative limit prices.  If the limit pricer escalates to
    market the order type is switched to ``"MKT"``.  ``prefer_rth`` determines
    the value of the regular trading hours flag.
    """

    limit_cfg = getattr(cfg, "limits", LimitsConfig())
    now = datetime.now(timezone.utc)
    orders: list[Order] = []

    for symbol, qty in plan.items():
        if symbol not in contracts or symbol not in quotes:
            raise KeyError(f"missing data for {symbol}")

        if qty == 0:
            raise ValueError(f"non-zero quantity required for {symbol}")

        side = OrderSide.BUY if qty > 0 else OrderSide.SELL
        quantity = abs(qty)
        if not allow_fractional:
            # Round to the nearest whole share and drop zero-qty orders
            quantity = round(quantity)
        if quantity <= 0:
            continue

        contract = contracts[symbol]
        quote = quotes[symbol]

        order_type = OrderType.LIMIT if cfg.order_type == "LMT" else OrderType.MARKET
        limit_price: float | None = None

        if order_type is OrderType.LIMIT:
            tick = _min_tick(contract)
            if side is OrderSide.BUY:
                price, kind = limit_pricer.price_limit_buy(quote, tick, limit_cfg, now)
            else:
                price, kind = limit_pricer.price_limit_sell(quote, tick, limit_cfg, now)
            if kind == "MKT":
                order_type = OrderType.MARKET
            else:
                limit_price = price

        orders.append(
            Order(
                contract=contract,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                rth=RTH.RTH_ONLY if prefer_rth else RTH.ALL_HOURS,
            )
        )

    return orders


def build_fx_order(
    fx_plan: FxPlan, contract: Contract, prefer_rth: bool = True
) -> Order:
    """Return an FX ``Order`` from ``fx_plan``.

    The plan's quantity is rounded to two decimal places while limit prices are
    rounded to the nearest pip (``0.0001``) or the contract's ``min_tick`` if it
    specifies one.  ``fx_plan.side`` determines the order side.  ``fx_plan`` is
    assumed to describe a required conversion; callers should ensure
    ``fx_plan.need_fx`` before invoking this function.  ``prefer_rth`` controls
    whether orders restrict execution to regular trading hours.
    """

    qty = round(fx_plan.qty, 2)
    if qty <= 0:
        raise ValueError("fx quantity must be positive")

    side = OrderSide(fx_plan.side)
    order_type = OrderType.LIMIT if fx_plan.order_type == "LMT" else OrderType.MARKET
    limit_price: float | None = None

    if order_type is OrderType.LIMIT:
        if fx_plan.limit_price is None:
            raise ValueError("limit price required for LMT FX order")
        tick = getattr(contract, "min_tick", 0.0001) or 0.0001
        limit_price = round(round(fx_plan.limit_price / tick) * tick, 4)

    return Order(
        contract=contract,
        side=side,
        quantity=qty,
        order_type=order_type,
        limit_price=limit_price,
        rth=RTH.RTH_ONLY if prefer_rth else RTH.ALL_HOURS,
    )
