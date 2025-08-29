"""Order execution infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import time
from typing import Sequence

from . import safety
from .fx_engine import FxPlan
from .ibkr_provider import (
    Fill,
    IBKRProvider,
    Order,
    OrderSide,
    PacingError as ProviderPacingError,
    ProviderError,
    ResolutionError as ProviderResolutionError,
)

__all__ = [
    "OrderExecutionOptions",
    "OrderExecutionResult",
    "ExecutionError",
    "ConnectionError",
    "PacingError",
    "ResolutionError",
    "execute_orders",
]


class ExecutionError(RuntimeError):
    """Base class for order execution errors.

    ``exit_code`` provides a process exit status that callers can use to
    terminate the application with a meaningful code.
    """

    exit_code: int = 1

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        # Instance attribute for easy access from callers.
        self.exit_code = self.__class__.exit_code


class ConnectionError(ExecutionError):
    """Raised when communication with the provider fails."""

    exit_code = 2


class PacingError(ExecutionError):
    """Raised when provider pacing limits are exceeded."""

    exit_code = 3


class ResolutionError(ExecutionError):
    """Raised when a contract cannot be resolved by the provider."""

    exit_code = 4


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


@dataclass
class OrderExecutionResult:
    """Return value from :func:`execute_orders` when orders are placed.

    Attributes
    ----------
    fills:
        Fills returned by the provider.
    canceled:
        Orders that were canceled due to timeout or partial fills.
    timed_out:
        ``True`` if any batch timed out while waiting for fills.
    sell_proceeds:
        Cash realized from ``sell_orders`` fills.
    """

    fills: list[Fill]
    canceled: list[Order]
    timed_out: bool = False
    sell_proceeds: float = 0.0


def execute_orders(
    ib: IBKRProvider,
    *,
    fx_orders: Sequence[Order] | None = None,
    sell_orders: Sequence[Order] | None = None,
    buy_orders: Sequence[Order] | None = None,
    fx_plan: FxPlan | None = None,
    options: OrderExecutionOptions | None = None,
    available_cash: float | None = None,
    max_leverage: float = 1.0,
) -> OrderExecutionResult | Sequence[Order]:
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
    available_cash:
        Optional cash available for purchasing securities before considering
        sell proceeds.
    max_leverage:
        Maximum multiple of ``available_cash`` that may be spent on BUYS.

    Returns
    -------
    OrderExecutionResult | Sequence[Order]
        Planned orders when ``report_only`` or ``dry_run`` is set, otherwise
        execution details including fills and canceled orders.
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

    result = OrderExecutionResult(fills=[], canceled=[])

    def _translate_error(exc: Exception) -> ExecutionError:
        if isinstance(exc, ProviderPacingError):
            return PacingError(str(exc))
        if isinstance(exc, ProviderResolutionError):
            return ResolutionError(str(exc))
        if isinstance(exc, ProviderError):
            return ExecutionError(str(exc))
        if isinstance(exc, (OSError, TimeoutError)):
            return ConnectionError(str(exc))
        return ExecutionError(str(exc))

    def _submit_group(group_name: str, group: Sequence[Order]) -> None:
        if not group:
            return
        cap = options.concurrency_cap
        if cap is None or cap == 0:
            batches = [list(group)]
        else:
            nonzero_cap = cap
            batches = [list(group[i : i + nonzero_cap]) for i in range(0, len(group), nonzero_cap)]
        for batch in batches:
            try:
                order_ids = [ib.place_order(o) for o in batch]
            except Exception as exc:  # pragma: no cover - defensive
                raise _translate_error(exc) from exc
            logger.info("orders_submitted", extra={"group": group_name, "count": len(batch)})
            id_to_order = dict(zip(order_ids, batch))
            timed_out = False
            try:
                batch_fills = list(ib.wait_for_fills(order_ids))
            except TimeoutError:
                batch_fills = []
                timed_out = True
            except Exception as exc:  # pragma: no cover - defensive
                raise _translate_error(exc) from exc
            result.fills.extend(batch_fills)
            remaining = set(order_ids)
            for fill in batch_fills:
                oid = getattr(fill, "order_id", None)
                if oid is not None and oid in remaining:
                    remaining.remove(oid)
                    continue
                for oid in list(remaining):
                    order = id_to_order[oid]
                    if (
                        fill.contract.symbol == order.contract.symbol
                        and fill.side == order.side
                        and fill.quantity == order.quantity
                    ):
                        remaining.remove(oid)
                        break
            for oid in remaining:
                ib.cancel(oid)
                result.canceled.append(id_to_order[oid])
            if timed_out:
                result.timed_out = True
            logger.info("orders_filled", extra={"group": group_name, "count": len(batch_fills)})
            if remaining:
                logger.warning(
                    "orders_unfilled",
                    extra={"group": group_name, "count": len(remaining), "timeout": timed_out},
                )

    _submit_group("fx", fx_orders)

    if fx_plan and fx_plan.wait_for_fill_seconds > 0:
        logger.info("fx_pause", extra={"seconds": fx_plan.wait_for_fill_seconds})
        time.sleep(fx_plan.wait_for_fill_seconds)

    pre_sell = len(result.fills)
    _submit_group("sell", sell_orders)

    # capture proceeds from sell fills for later use
    sell_fills = [f for f in result.fills[pre_sell:] if f.side is OrderSide.SELL]
    result.sell_proceeds = sum(f.quantity * f.price for f in sell_fills)

    # scale buys to respect available cash and leverage
    if available_cash is not None and buy_orders:
        buying_power = available_cash * max_leverage + result.sell_proceeds

        def _notional(order: Order) -> float:
            price = order.limit_price
            if price is None:
                quote = ib.get_quote(order.contract)
                price = quote.ask if order.side is OrderSide.BUY else quote.bid
                if price is None:
                    price = quote.last
            if price is None:
                raise RuntimeError("cannot determine order notional")
            return order.quantity * price

        total_notional = sum(_notional(o) for o in buy_orders)
        if total_notional > 0 and buying_power < total_notional:
            scale = buying_power / total_notional
            logger.info("buy_scaled", extra={"scale": scale})
            buy_orders = [replace(o, quantity=o.quantity * scale) for o in buy_orders]

    _submit_group("buy", buy_orders)

    logger.info("fills_collected", extra={"count": len(result.fills)})
    return result
