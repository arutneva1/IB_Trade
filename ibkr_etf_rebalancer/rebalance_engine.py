"""Simplified portfolio rebalancing helpers.

The real project contains a fairly involved rebalancing engine that
interfaces with Interactive Brokers.  For the unit tests in this kata we
only implement the small piece of logic that decides *what* trades should be
executed in order to move a portfolio from its current weights to a desired
target.  The function below intentionally works with a very small input set
so that the behaviour is easy to reason about in tests.

Overview
--------

``generate_orders`` accepts dictionaries describing the target portfolio and
the currently held weights.  Differences outside the provided tolerance band
are converted into buy or sell orders.  A few additional constraints are
modelled:

``min_order``
    Notional value below this threshold is ignored.

``max_leverage``
    Gross exposure may not exceed ``max_leverage`` times the account equity.
    Sells are applied first to free up buying power and then buys are scaled
    proportionally if the leverage limit would otherwise be breached.  This
    allows scenarios such as ``CASH=-0.50`` (i.e. gross ``150%``) where the
    account is borrowing cash.

``allow_fractional``
    When ``False`` the resulting orders are rounded to whole shares using the
    provided ``prices`` mapping.

The function returns a mapping of symbol to share count where a positive
number represents a buy and a negative number represents a sell.  Any symbol
named ``"CASH"`` is ignored – cash exposure is represented implicitly by the
other trades and the leverage constraints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

from .config import FXConfig, PricingConfig
from .fx_engine import FxPlan, plan_fx_if_needed
from .pricing import QuoteProvider


@dataclass
class OrderPlan:
    """Planned equity orders and any dropped trades."""

    orders: Dict[str, float] = field(default_factory=dict)
    dropped: Dict[str, str] = field(default_factory=dict)


def _get_band(bands: float | Mapping[str, float], symbol: str) -> float:
    """Helper to fetch the tolerance band for ``symbol``.

    ``bands`` may either be a single float applied to all symbols or a
    mapping of per‑symbol tolerances.
    """

    if isinstance(bands, Mapping):
        return bands.get(symbol, 0.0)
    return bands


def generate_orders(
    targets: Mapping[str, float],
    current: Mapping[str, float],
    prices: Mapping[str, float],
    total_equity: float,
    *,
    bands: float | Mapping[str, float] = 0.0,
    min_order: float = 0.0,
    max_leverage: float = 1.0,
    cash_buffer_pct: float = 0.0,
    maintenance_buffer_pct: float = 0.0,
    allow_fractional: bool = True,
    trigger_mode: str = "per_holding",
    portfolio_total_band_bps: float = 0.0,
) -> OrderPlan:
    """Create rebalance orders for the supplied portfolio.

    Parameters
    ----------
    targets, current:
        Dictionaries mapping ``symbol`` to target/current weights.  The
        weights are expressed as fractions of account equity (``0.25`` for
        ``25%``).  The special key ``"CASH"`` may appear with a negative
        weight to indicate a margin loan.  Any missing symbols default to
        ``0``.
    prices:
        Mapping of ``symbol`` to last trade price.  These are used to convert
        notional differences into share counts and for enforcing whole share
        trading when ``allow_fractional`` is ``False``.
    total_equity:
        Dollar value of the account.  All order sizes are based on this
        figure.
    bands:
        Absolute tolerance bands.  A position whose target/current difference
        falls within the band is left untouched.  ``bands`` may be a single
        float applied to all symbols or a mapping of per‑symbol tolerances.
    min_order:
        Minimum notional value for an order to be considered.  Anything
        smaller is ignored.
    max_leverage:
        Maximum allowed gross exposure expressed as a multiple of
        ``total_equity``.  A value of ``1.5`` corresponds to ``150%`` gross
        and ``CASH=-0.50``.
    cash_buffer_pct:
        Percentage of ``total_equity`` that must remain as cash after
        rebalancing (e.g. ``5`` for ``5%``).  Buys are scaled down if
        necessary to leave this cushion unspent.
    maintenance_buffer_pct:
        Additional headroom against the leverage cap expressed as a
        percentage of ``total_equity``.  Buys are scaled to keep gross
        exposure plus this buffer within ``max_leverage``.
    allow_fractional:
        When ``False`` orders are rounded to whole shares.
    trigger_mode:
        ``"per_holding"`` (default) evaluates bands per position.  ``"total_drift"``
        sums absolute drifts across the portfolio and triggers rebalancing if
        that total exceeds ``portfolio_total_band_bps``.
    portfolio_total_band_bps:
        Threshold in basis points for ``trigger_mode="total_drift"``.

    Returns
    -------
    OrderPlan
        ``OrderPlan.orders`` maps ``symbol`` to number of shares to buy
        (positive) or sell (negative).  ``OrderPlan.dropped`` records reasons
        for any trades that were ignored.
    """

    valid_modes = {"per_holding", "total_drift"}
    if trigger_mode not in valid_modes:
        raise ValueError(f"Unsupported trigger_mode: {trigger_mode}")

    # ------------------------------------------------------------------
    # Determine raw desired order sizes in dollars
    orders_value: Dict[str, float] = {}
    dropped: Dict[str, str] = {}
    symbols = set(targets) | set(current)
    diffs: Dict[str, float] = {}
    outside_band: Dict[str, float] = {}
    for symbol in symbols:
        if symbol == "CASH":
            continue
        diff = targets.get(symbol, 0.0) - current.get(symbol, 0.0)
        diffs[symbol] = diff
        if abs(diff) > _get_band(bands, symbol):
            outside_band[symbol] = diff

    if outside_band:
        actionable = outside_band
    else:
        total_drift_bps = round(sum(abs(d) for d in diffs.values()) * 10_000, 8)
        if trigger_mode == "total_drift" and total_drift_bps > portfolio_total_band_bps:
            actionable = {sym: d for sym, d in diffs.items() if d != 0}
        else:
            actionable = {}

    for symbol, diff in actionable.items():
        # Round to cents to avoid downstream floating point artefacts when
        # converting back to share counts.
        value = round(diff * total_equity, 2)
        if abs(value) < min_order:
            dropped[symbol] = (
                f"notional {abs(value):.2f} below min_order {min_order:.2f}"
            )
            continue
        orders_value[symbol] = value

    # Nothing to do
    if not orders_value:
        return OrderPlan(orders={}, dropped=dropped)

    # ------------------------------------------------------------------
    # Apply sells first to free up buying power
    cash = current.get("CASH", 0.0) * total_equity
    gross = sum(current.get(sym, 0.0) * total_equity for sym in current if sym != "CASH")
    sells = {sym: val for sym, val in orders_value.items() if val < 0}
    buys = {sym: val for sym, val in orders_value.items() if val > 0}

    # Rebuild ``orders_value`` so dropped buys don't leave stale entries
    orders_value = {}

    for symbol, value in sells.items():
        cash -= value  # value is negative -> increases cash
        gross += value  # reduces gross exposure
        orders_value[symbol] = value

    # ------------------------------------------------------------------
    # Scale buys if they would exceed cash or leverage limits
    cash_buffer = total_equity * cash_buffer_pct / 100.0
    maint_buffer = total_equity * maintenance_buffer_pct / 100.0
    available_leverage = max_leverage * total_equity - gross - maint_buffer
    available_cash = cash - cash_buffer if cash_buffer_pct > 0 else float("inf")
    available = min(available_leverage, available_cash)
    total_buy_value = sum(buys.values())
    scale = 1.0
    if total_buy_value > available and total_buy_value > 0:
        scale = max(available, 0.0) / total_buy_value

    for symbol, value in buys.items():
        scaled_value = value * scale
        if abs(scaled_value) < min_order:
            # Drop any orders that fell below ``min_order`` after scaling
            dropped[symbol] = (
                f"notional {abs(scaled_value):.2f} below min_order {min_order:.2f}"
            )
            continue
        cash -= scaled_value
        gross += scaled_value
        orders_value[symbol] = scaled_value

    if not orders_value:
        return OrderPlan(orders={}, dropped=dropped)

    # ------------------------------------------------------------------
    # Convert notional values to share counts
    orders_shares: Dict[str, float] = {}
    for symbol, value in orders_value.items():
        price = prices[symbol]
        shares = value / price
        if not allow_fractional:
            # Round towards zero would leave us short on buys or long on sells
            # so we round outwards instead.
            if shares > 0:
                shares = math.ceil(shares)
            else:
                shares = math.floor(shares)
            if shares == 0:
                continue
        if shares < 0:
            current_shares = current.get(symbol, 0.0) * total_equity / price
            max_sell = math.floor(current_shares) if not allow_fractional else current_shares
            if abs(shares) > max_sell:
                if max_sell > 0:
                    shares = -max_sell
                else:
                    continue
        orders_shares[symbol] = shares

    return OrderPlan(orders=orders_shares, dropped=dropped)


def plan_rebalance_with_fx(
    targets: Mapping[str, float],
    current: Mapping[str, float],
    prices: Mapping[str, float],
    total_equity: float,
    *,
    fx_cfg: FXConfig,
    quote_provider: QuoteProvider,
    pricing_cfg: PricingConfig,
    funding_currency: str = "CAD",
    **kwargs: Any,
) -> tuple[OrderPlan, FxPlan]:
    """Plan equity trades and any required FX conversion."""

    funding_cash = float(kwargs.pop("funding_cash", kwargs.pop("cad_cash", 0.0)))
    funding_currency = funding_currency.upper()
    allowed_funding = {c.upper() for c in fx_cfg.funding_currencies}
    if funding_currency not in allowed_funding:
        raise ValueError(f"unsupported funding currency: {funding_currency}")
    usd_cash = current.get("CASH", 0.0) * total_equity

    pair = f"{fx_cfg.base_currency}.{funding_currency}"

    # First pass: assume funding cash is converted to size desired equity orders
    planning_current = dict(current)
    planning_current["CASH"] = (usd_cash + funding_cash) / total_equity
    planning_plan = generate_orders(targets, planning_current, prices, total_equity, **kwargs)

    usd_buy_notional = sum(
        shares * prices[symbol]
        for symbol, shares in planning_plan.orders.items()
        if shares > 0
    )
    usd_sell_notional = sum(
        -shares * prices[symbol]
        for symbol, shares in planning_plan.orders.items()
        if shares < 0
    )
    usd_cash_after_sells = usd_cash + usd_sell_notional

    fx_plan = FxPlan(
        need_fx=False,
        pair=pair,
        side="BUY",
        usd_notional=0.0,
        est_rate=0.0,
        qty=0.0,
        order_type=fx_cfg.order_type,
        limit_price=None,
        route=fx_cfg.route,
        wait_for_fill_seconds=fx_cfg.wait_for_fill_seconds,
        reason="fx disabled" if not fx_cfg.enabled else "sufficient USD cash",
    )

    need_fx = fx_cfg.enabled and (
        usd_buy_notional > usd_cash_after_sells or fx_cfg.convert_mode == "always_top_up"
    )
    if need_fx:
        try:
            fx_rate = quote_provider.get_price(
                pair,
                pricing_cfg.price_source,
                pricing_cfg.fallback_to_snapshot,
            )
        except Exception as exc:
            fx_plan = FxPlan(
                need_fx=False,
                pair=pair,
                side="BUY",
                usd_notional=0.0,
                est_rate=0.0,
                qty=0.0,
                order_type=fx_cfg.order_type,
                limit_price=None,
                route=fx_cfg.route,
                wait_for_fill_seconds=fx_cfg.wait_for_fill_seconds,
                reason=f"fx price unavailable: {exc}",
            )
        else:
            try:
                fx_quote = quote_provider.get_quote(pair)
            except Exception:
                fx_quote = None
            usd_needed = usd_buy_notional
            if fx_cfg.convert_mode == "always_top_up":
                usd_needed = max(usd_buy_notional, fx_cfg.min_fx_order_usd)
            fx_plan = plan_fx_if_needed(
                usd_needed=usd_needed,
                usd_cash=usd_cash_after_sells,
                funding_cash=funding_cash,
                fx_quote=fx_quote,
                cfg=fx_cfg,
                fx_price=fx_rate,
                funding_currency=funding_currency,
            )

    final_cash = usd_cash + fx_plan.usd_notional
    final_current = dict(current)
    final_current["CASH"] = final_cash / total_equity
    final_plan = generate_orders(targets, final_current, prices, total_equity, **kwargs)

    return final_plan, fx_plan


__all__ = ["generate_orders", "plan_rebalance_with_fx", "OrderPlan"]
