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
from typing import Dict, Mapping


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
) -> Dict[str, float]:
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
        rebalancing.  Buys are scaled down if necessary to leave this
        cushion unspent.
    maintenance_buffer_pct:
        Additional headroom against the leverage cap expressed as a
        percentage of ``total_equity``.  Buys are scaled to keep gross
        exposure plus this buffer within ``max_leverage``.
    allow_fractional:
        When ``False`` orders are rounded to whole shares.

    Returns
    -------
    Dict[str, float]
        Mapping of symbol to number of shares to buy (positive) or sell
        (negative).  Symbols for which no trade is required are omitted.
    """

    # ------------------------------------------------------------------
    # Determine raw desired order sizes in dollars
    orders_value: Dict[str, float] = {}
    symbols = set(targets) | set(current)
    for symbol in symbols:
        if symbol == "CASH":
            continue
        diff = targets.get(symbol, 0.0) - current.get(symbol, 0.0)
        if abs(diff) <= _get_band(bands, symbol):
            continue
        # Round to cents to avoid downstream floating point artefacts when
        # converting back to share counts.
        value = round(diff * total_equity, 2)
        if abs(value) < min_order:
            continue
        orders_value[symbol] = value

    # Nothing to do
    if not orders_value:
        return {}

    # ------------------------------------------------------------------
    # Apply sells first to free up buying power
    cash = current.get("CASH", 0.0) * total_equity
    gross = sum(current.get(sym, 0.0) * total_equity for sym in current if sym != "CASH")
    sells = {sym: val for sym, val in orders_value.items() if val < 0}
    buys = {sym: val for sym, val in orders_value.items() if val > 0}

    for symbol, value in sells.items():
        cash -= value  # value is negative -> increases cash
        gross += value  # reduces gross exposure
        orders_value[symbol] = value

    # ------------------------------------------------------------------
    # Scale buys if they would exceed cash or leverage limits
    cash_buffer = total_equity * cash_buffer_pct / 100.0
    maint_buffer = total_equity * maintenance_buffer_pct / 100.0
    available_leverage = max_leverage * total_equity - gross - maint_buffer
    available_cash = (
        cash - cash_buffer if cash_buffer_pct > 0 else float("inf")
    )
    available = min(available_leverage, available_cash)
    total_buy_value = sum(buys.values())
    scale = 1.0
    if total_buy_value > available and total_buy_value > 0:
        scale = max(available, 0.0) / total_buy_value

    for symbol, value in buys.items():
        scaled_value = value * scale
        cash -= scaled_value
        gross += scaled_value
        orders_value[symbol] = scaled_value

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
        orders_shares[symbol] = shares

    return orders_shares


__all__ = ["generate_orders"]
