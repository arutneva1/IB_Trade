"""Order execution infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .ibkr_provider import Fill, IBKRProvider, Order

__all__ = ["OrderExecutionOptions", "execute_orders"]


@dataclass
class OrderExecutionOptions:
    """Options controlling how orders are executed.

    Parameters
    ----------
    report_only:
        Generate reports without sending orders.
    dry_run:
        Simulate the execution flow without side effects.
    yes:
        Automatically answer affirmatively to confirmation prompts.
    """

    report_only: bool = False
    dry_run: bool = False
    yes: bool = False


def execute_orders(
    ib: IBKRProvider,
    *,
    fx_orders: Sequence[Order] | None = None,
    sell_orders: Sequence[Order] | None = None,
    buy_orders: Sequence[Order] | None = None,
) -> Sequence[Fill]:
    """Place FX, then SELL, then BUY orders using ``ib``.

    Each group of orders is submitted and awaited before the next group is
    processed to ensure deterministic sequencing.

    Parameters
    ----------
    ib:
        Provider used for order placement.
    fx_orders, sell_orders, buy_orders:
        Order groups to place sequentially. ``None`` is treated as an empty
        sequence.

    Returns
    -------
    Sequence[Fill]
        Fills returned by the provider for all orders.
    """

    fx_orders = fx_orders or ()
    sell_orders = sell_orders or ()
    buy_orders = buy_orders or ()

    fills: list[Fill] = []
    for group in (fx_orders, sell_orders, buy_orders):
        if not group:
            continue
        order_ids = [ib.place_order(o) for o in group]
        fills.extend(ib.wait_for_fills(order_ids))
    return fills
