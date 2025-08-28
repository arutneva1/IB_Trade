"""Compute portfolio level exposure and cash balances.

This module provides a small helper used throughout the tests to reason about
an account's current state.  The real project contains a much richer
implementation but for the exercises we only need a subset of the behaviour:

* Derive per-symbol market values and weights from position quantities and
  prices.
* Report gross and net exposure relative to available equity.
* Track cash balances for USD and CAD while supporting a configurable USD cash
  buffer which is excluded from the exposure calculations.

Only USD denominated assets participate in exposure and weight calculations; an
optional CAD cash balance is carried through verbatim but ignored when
normalising weights.  The return type intentionally mirrors a tiny portion of
the production system making it convenient for unit tests to assert on specific
figures.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from typing import Mapping


@dataclass(frozen=True)
class AccountSnapshot:
    """Simple view of the account after normalisation."""

    market_values: OrderedDict[str, float]
    """Per-symbol USD market values."""

    weights: OrderedDict[str, float]
    """Normalised position weights keyed by symbol and ``"CASH"``."""

    cash_by_currency: Mapping[str, float]
    """Reported cash balances keyed by ISO currency code."""

    usd_cash: float
    """Reported USD cash balance (before any buffer adjustment)."""

    cad_cash: float
    """Reported CAD cash balance."""

    gross_exposure: float
    """Sum of absolute asset exposure relative to equity."""

    net_exposure: float
    """Net exposure including USD cash (should equal ``1.0``)."""

    total_equity: float
    """Net asset value including USD cash before any buffer adjustment."""

    effective_equity: float
    """Equity available for allocation after applying any cash buffer."""


def compute_account_state(
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    cash_balances: Mapping[str, float],
    *,
    cash_buffer_pct: float = 0.0,
) -> AccountSnapshot:
    """Return the :class:`AccountSnapshot` for *positions*.

    The function is pure and performs no side effects.  Prices must be provided
    for each symbol and be strictly positive.  Weights are derived using the
    available equity after applying ``cash_buffer_pct`` to the USD cash balance
    and include a ``"CASH"`` entry representing the remaining USD cash.  Non-USD
    cash balances are excluded from weight normalisation.  Due to floating point
    rounding the weights may not sum exactly to ``1.0`` but are expected to be
    within ``±1e-6``.

    Parameters
    ----------
    positions:
        Mapping of symbol to quantity.  Zero quantities are rejected.
    prices:
        Mapping of symbol to last trade price.  Prices must be positive and not
        NaN.
    cash_balances:
        Mapping of currency code (e.g. ``"USD"``/``"CAD"``) to amount.
    cash_buffer_pct:
        Fraction of the USD cash balance to exclude from exposure/weight
        calculations.
    """

    cash_by_currency = {ccy: float(amount) for ccy, amount in cash_balances.items()}
    usd_cash = float(cash_by_currency.get("USD", 0.0))
    cad_cash = float(cash_by_currency.get("CAD", 0.0))

    # Validate positions and compute their USD market value.
    market_values: OrderedDict[str, float] = OrderedDict()
    net_pos_val = 0.0
    gross_pos_val = 0.0
    for symbol, qty in positions.items():
        if qty == 0:
            raise ValueError("Zero quantity not allowed")
        if symbol not in prices:
            raise ValueError(f"Missing price for {symbol}")
        price = prices[symbol]
        if price <= 0 or math.isnan(price):
            raise ValueError(f"Invalid price for {symbol}")
        value = qty * price
        market_values[symbol] = value
        net_pos_val += value
        gross_pos_val += abs(value)

    total_equity = net_pos_val + usd_cash
    effective_usd_cash = usd_cash * (1.0 - cash_buffer_pct)
    effective_equity = net_pos_val + effective_usd_cash
    if effective_equity <= 0.0:
        raise ValueError("Account has zero equity")

    # Derive weights relative to the effective equity figure.
    weights = OrderedDict(
        (symbol, value / effective_equity) for symbol, value in sorted(market_values.items())
    )
    weights["CASH"] = effective_usd_cash / effective_equity

    gross = gross_pos_val / effective_equity
    net = (net_pos_val + effective_usd_cash) / effective_equity

    return AccountSnapshot(
        market_values=OrderedDict(sorted(market_values.items())),
        weights=weights,
        cash_by_currency=OrderedDict(sorted(cash_by_currency.items())),
        usd_cash=usd_cash,
        cad_cash=cad_cash,
        gross_exposure=gross,
        net_exposure=net,
        total_equity=total_equity,
        effective_equity=effective_equity,
    )


__all__ = ["AccountSnapshot", "compute_account_state"]
