"""Compute portfolio level exposure and cash balances.

This module provides a small helper used throughout the tests to reason about
an account's current state.  The real project contains a much richer
implementation but for the exercises we only need a subset of the behaviour:

* Derive per-symbol weights from position quantities and prices.
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


@dataclass
class AccountState:
    """Simple view of the account after normalisation."""

    weights: "OrderedDict[str, float]"
    """Normalised position weights keyed by symbol."""

    gross_exposure: float
    """Total long exposure relative to equity (always positive)."""

    net_exposure: float
    """Net exposure including cash (should equal ``1.0``)."""

    usd_cash: float
    """Reported USD cash balance (before any buffer adjustment)."""

    cad_cash: float
    """Reported CAD cash balance."""


def compute_account_state(
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    cash: Mapping[str, float],
    *,
    cash_buffer_pct: float,
) -> AccountState:
    """Return the :class:`AccountState` for *positions*.

    Parameters
    ----------
    positions:
        Mapping of symbol to quantity.  Quantities must be positive and every
        symbol requires a valid price entry in ``prices``.
    prices:
        Mapping of symbol to last trade price.  Prices must be positive and not
        NaN.
    cash:
        Mapping of currency code ("USD"/"CAD") to amount.
    cash_buffer_pct:
        Fraction of the USD cash balance to exclude from exposure/weight
        calculations.
    """

    # Extract cash balances before applying any buffer.
    usd_cash = float(cash.get("USD", 0.0))
    cad_cash = float(cash.get("CAD", 0.0))

    # Validate positions and compute their USD market value.
    position_values: dict[str, float] = {}
    total_pos_val = 0.0
    for symbol, qty in positions.items():
        if qty == 0:
            raise ValueError("Zero quantity not allowed")
        if symbol not in prices:
            raise ValueError(f"Missing price for {symbol}")
        price = prices[symbol]
        if price <= 0 or math.isnan(price):
            raise ValueError(f"Invalid price for {symbol}")
        value = qty * price
        position_values[symbol] = value
        total_pos_val += value

    # Account must have some equity (positions or USD cash after buffer).
    effective_usd_cash = usd_cash * (1.0 - cash_buffer_pct)
    equity = total_pos_val + effective_usd_cash
    if equity <= 0.0:
        raise ValueError("Account has zero equity")

    # Derive weights relative to the equity figure.
    weights = OrderedDict(
        (symbol, value / equity) for symbol, value in sorted(position_values.items())
    )

    gross = total_pos_val / equity
    net = (total_pos_val + effective_usd_cash) / equity

    return AccountState(
        weights=weights,
        gross_exposure=gross,
        net_exposure=net,
        usd_cash=usd_cash,
        cad_cash=cad_cash,
    )


__all__ = ["AccountState", "compute_account_state"]

