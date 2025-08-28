"""FX planning utilities.

This module provides a small pure function used by the rebalancing engine to
determine whether a foreign exchange conversion is required.  It performs the
math for sizing the order but does not talk to Interactive Brokers or any
external service – it simply returns a :class:`FxPlan` dataclass describing the
desired trade.

Rates follow the IB convention where a pair such as ``USD.CAD`` represents the
amount of *CAD* per one unit of *USD*.  Quantity is therefore expressed in
units of the base currency (USD for ``USD.CAD``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from .config import FXConfig
from . import pricing

__all__ = ["FxPlan", "plan_fx_if_needed"]


@dataclass(slots=True)
class FxPlan:
    """Planned FX conversion.

    Attributes
    ----------
    need_fx:
        ``True`` when a conversion should be attempted.
    pair:
        Currency pair in ``BASE.QUOTE`` form (e.g. ``"USD.CAD"``).
    side:
        ``"BUY"`` when raising the base currency, ``"SELL"`` otherwise.
    usd_notional:
        USD amount we wish to obtain after applying buffers and caps.
    est_rate:
        Estimated FX rate used for sizing (CAD per USD).
    qty:
        Order quantity expressed in base currency units.  For ``USD.CAD`` this
        equals ``usd_notional``.
    order_type:
        Order type to use (``"MKT"`` or ``"LMT"``).
    limit_price:
        Limit price when ``order_type`` is ``"LMT"``; otherwise ``None``.
    route:
        IBKR venue for the FX order (e.g. ``"IDEALPRO"``).
    wait_for_fill_seconds:
        Seconds to pause before placing dependent ETF orders.
    reason:
        Human readable explanation of the decision.
    """

    need_fx: bool
    pair: str
    side: Literal["BUY", "SELL"]
    usd_notional: float
    est_rate: float
    qty: float
    order_type: Literal["MKT", "LMT"]
    limit_price: float | None
    route: str
    wait_for_fill_seconds: int
    reason: str


def _round_price(value: float) -> float:
    """Round *value* to the nearest pip (``0.0001``)."""

    return round(value, 4)


def _round_qty(value: float) -> float:
    """Round *value* to two decimal places (``0.01`` units)."""

    return round(value, 2)


def plan_fx_if_needed(
    usd_needed: float,
    usd_cash: float,
    cad_cash: float,
    fx_quote: pricing.Quote | None,
    cfg: FXConfig,
    *,
    now: datetime | None = None,
) -> FxPlan:
    """Return an :class:`FxPlan` describing any required FX conversion.

    Parameters
    ----------
    usd_needed:
        Total USD required to fund upcoming purchases.
    usd_cash:
        Current USD cash on hand.
    cad_cash:
        Available CAD cash.  If this is zero the function will return a plan
        with ``need_fx=False`` because there is nothing to convert.
    fx_quote:
        A :class:`pricing.Quote` for the ``USD.CAD`` pair.  When ``None`` or
        stale the function returns ``need_fx=False`` with a reason.
    cfg:
        FX configuration settings.
    """

    pair = f"{cfg.base_currency}.CAD"
    side: Literal["BUY", "SELL"] = "BUY"
    now = now or datetime.now(timezone.utc)

    if cfg.prefer_market_hours and now.weekday() >= 5:
        return FxPlan(
            need_fx=False,
            pair=pair,
            side=side,
            usd_notional=0.0,
            est_rate=0.0,
            qty=0.0,
            order_type=cfg.order_type,
            limit_price=None,
            route=cfg.route,
            wait_for_fill_seconds=cfg.wait_for_fill_seconds,
            reason="outside market hours",
        )

    # Calculate the USD shortfall and apply the buffer.
    shortfall = max(0.0, usd_needed - usd_cash)
    if shortfall == 0:
        return FxPlan(
            need_fx=False,
            pair=pair,
            side=side,
            usd_notional=0.0,
            est_rate=0.0,
            qty=0.0,
            order_type=cfg.order_type,
            limit_price=None,
            route=cfg.route,
            wait_for_fill_seconds=cfg.wait_for_fill_seconds,
            reason="no USD shortfall",
        )

    if cad_cash <= 0:
        return FxPlan(
            need_fx=False,
            pair=pair,
            side=side,
            usd_notional=0.0,
            est_rate=0.0,
            qty=0.0,
            order_type=cfg.order_type,
            limit_price=None,
            route=cfg.route,
            wait_for_fill_seconds=cfg.wait_for_fill_seconds,
            reason="no CAD cash available",
        )

    buffered = shortfall * (1 + cfg.fx_buffer_bps / 10_000)

    if buffered < cfg.min_fx_order_usd:
        reason = f"shortfall {buffered:.2f} below min {cfg.min_fx_order_usd}"  # noqa: E501
        return FxPlan(
            need_fx=False,
            pair=pair,
            side=side,
            usd_notional=0.0,
            est_rate=0.0,
            qty=0.0,
            order_type=cfg.order_type,
            limit_price=None,
            route=cfg.route,
            wait_for_fill_seconds=cfg.wait_for_fill_seconds,
            reason=reason,
        )

    usd_notional = buffered
    if cfg.max_fx_order_usd is not None:
        usd_notional = min(usd_notional, cfg.max_fx_order_usd)

    if fx_quote is None:
        return FxPlan(
            need_fx=False,
            pair=pair,
            side=side,
            usd_notional=0.0,
            est_rate=0.0,
            qty=0.0,
            order_type=cfg.order_type,
            limit_price=None,
            route=cfg.route,
            wait_for_fill_seconds=cfg.wait_for_fill_seconds,
            reason="no FX quote",
        )

    if pricing.is_stale(fx_quote, now, stale_quote_seconds=10):
        return FxPlan(
            need_fx=False,
            pair=pair,
            side=side,
            usd_notional=0.0,
            est_rate=0.0,
            qty=0.0,
            order_type=cfg.order_type,
            limit_price=None,
            route=cfg.route,
            wait_for_fill_seconds=cfg.wait_for_fill_seconds,
            reason="stale FX quote",
        )

    try:
        mid = fx_quote.mid()
    except ValueError:
        return FxPlan(
            need_fx=False,
            pair=pair,
            side=side,
            usd_notional=0.0,
            est_rate=0.0,
            qty=0.0,
            order_type=cfg.order_type,
            limit_price=None,
            route=cfg.route,
            wait_for_fill_seconds=cfg.wait_for_fill_seconds,
            reason="incomplete FX quote",
        )

    if cfg.use_mid_for_planning:
        est_rate = fx_quote.mid()
    else:
        if side == "BUY":
            assert fx_quote.ask is not None
            est_rate = fx_quote.ask
        else:
            assert fx_quote.bid is not None
            est_rate = fx_quote.bid
    est_rate = _round_price(est_rate)

    qty = _round_qty(usd_notional)
    usd_notional = qty

    limit_price: float | None = None
    if cfg.order_type == "LMT":
        offset = mid * (cfg.limit_slippage_bps / 10_000)
        price = mid + offset if side == "BUY" else mid - offset
        limit_price = _round_price(price)

    reason = f"fund USD shortfall of {shortfall:.2f} with buffer {cfg.fx_buffer_bps}bps"

    return FxPlan(
        need_fx=True,
        pair=pair,
        side=side,
        usd_notional=usd_notional,
        est_rate=est_rate,
        qty=qty,
        order_type=cfg.order_type,
        limit_price=limit_price,
        route=cfg.route,
        wait_for_fill_seconds=cfg.wait_for_fill_seconds,
        reason=reason,
    )
