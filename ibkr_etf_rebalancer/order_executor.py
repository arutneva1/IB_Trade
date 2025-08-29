"""Order execution infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
import logging
from typing import Sequence

from . import safety
from .fx_engine import FxPlan
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
    concurrency_cap:
        Maximum number of concurrent orders to maintain. ``None`` for no cap.
    prefer_rth:
        Require regular trading hours before placing orders.
    """

    report_only: bool = False
    dry_run: bool = False
    yes: bool = False
    concurrency_cap: int | None = None
    prefer_rth: bool = False


def execute_orders(
    ib: IBKRProvider,
    *,
    fx_orders: Sequence[Order] | None = None,
    sell_orders: Sequence[Order] | None = None,
    buy_orders: Sequence[Order] | None = None,
    fx_plan: FxPlan | None = None,
    options: OrderExecutionOptions | None = None,
) -> Sequence[Fill] | Sequence[Order]:
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
    fx_plan:
        Optional :class:`FxPlan` used to insert a pause after FX fills.
    options:
        Execution options controlling behaviour.

    Returns
    -------
    Sequence[Fill] | Sequence[Order]
        Planned orders when ``report_only`` or ``dry_run`` is set, otherwise
        fills returned by the provider for all orders.
    """

    logger = logging.getLogger(__name__)
    options = options or OrderExecutionOptions()

    safety.check_kill_switch(ib.options.kill_switch)
    safety.ensure_paper_trading(ib.options.paper, ib.options.live)
    safety.ensure_regular_trading_hours(datetime.now(timezone.utc), options.prefer_rth)
    safety.require_confirmation("Proceed with order placement?", options.yes)

    fx_orders = fx_orders or ()
    sell_orders = sell_orders or ()
    buy_orders = buy_orders or ()

    planned = list(fx_orders) + list(sell_orders) + list(buy_orders)

    logger.info("planned_orders", extra={"count": len(planned)})
    if options.report_only or options.dry_run or ib.options.dry_run:
        return planned

    fills: list[Fill] = []

    def _submit_group(group_name: str, group: Sequence[Order]) -> None:
        if not group:
            return
        cap = options.concurrency_cap
        if cap is None or cap == 0:
            batches = [list(group)]
        else:
            nonzero_cap = cap
            batches = [
                list(group[i : i + nonzero_cap])
                for i in range(0, len(group), nonzero_cap)
            ]
        for batch in batches:
            order_ids = [ib.place_order(o) for o in batch]
            logger.info("orders_submitted", extra={"group": group_name, "count": len(batch)})
            fills.extend(ib.wait_for_fills(order_ids))
            logger.info("orders_filled", extra={"group": group_name, "count": len(order_ids)})

    _submit_group("fx", fx_orders)

    if fx_plan and fx_plan.wait_for_fill_seconds > 0:
        logger.info("fx_pause", extra={"seconds": fx_plan.wait_for_fill_seconds})
        time.sleep(fx_plan.wait_for_fill_seconds)

    _submit_group("sell", sell_orders)
    _submit_group("buy", buy_orders)

    logger.info("fills_collected", extra={"count": len(fills)})
    return fills
