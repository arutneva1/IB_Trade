"""Utilities for loading model portfolios from CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict
import csv
import math

VALID_PORTFOLIOS = {"SMURF", "BADASS", "GLTR"}
TOLERANCE = 1e-4  # 0.01%


@dataclass
class PortfolioRow:
    """Single row in a portfolio CSV file."""

    portfolio: str
    symbol: str
    target_pct: float  # stored as fraction (0-1); CASH may be negative


class PortfolioError(ValueError):
    """Raised when the portfolio CSV fails validation."""


def load_portfolios(csv_path: Path, *, allow_margin: bool = False) -> Dict[str, Dict[str, float]]:
    """Read a portfolio CSV and return a mapping of model -> weights.

    Parameters
    ----------
    csv_path:
        Path to the ``portfolios.csv`` file.
    allow_margin:
        When ``True``, allow a single ``CASH`` row per portfolio with a
        negative percentage representing borrowed cash.

    Returns
    -------
    dict
        Mapping of portfolio name (e.g. ``SMURF``) to ``{symbol: weight}``
        where ``weight`` is a fractional value (e.g. ``0.4`` for ``40``).

    Raises
    ------
    PortfolioError
        If the CSV is malformed or violates validation rules.
    """

    rows: list[PortfolioRow] = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        required = {"portfolio", "symbol", "target_pct"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = required - set(reader.fieldnames or [])
            raise PortfolioError(f"CSV missing required columns: {', '.join(sorted(missing))}")
        for raw in reader:
            portfolio = raw["portfolio"].strip().upper()
            symbol = raw["symbol"].strip().upper()
            try:
                pct = float(raw["target_pct"]) / 100.0
            except ValueError as exc:  # pragma: no cover - defensive
                raise PortfolioError(
                    f"Invalid target_pct '{raw['target_pct']}' for {portfolio}:{symbol}"
                ) from exc

            if portfolio not in VALID_PORTFOLIOS:
                raise PortfolioError(
                    f"Unknown portfolio '{portfolio}' (expected one of {sorted(VALID_PORTFOLIOS)})"
                )

            if symbol != "CASH":
                if not math.isfinite(pct):
                    raise PortfolioError(
                        f"Portfolio {portfolio}: symbol {symbol} has non-finite target_pct {raw['target_pct']}"
                    )
                if pct < 0:
                    raise PortfolioError(
                        f"Portfolio {portfolio}: symbol {symbol} has negative target_pct {pct*100:.2f}%"
                    )
                if pct > 1:
                    raise PortfolioError(
                        f"Portfolio {portfolio}: symbol {symbol} target_pct {pct*100:.2f}% exceeds 100%"
                    )
            elif not math.isfinite(pct):
                raise PortfolioError(
                    f"Portfolio {portfolio}: CASH row has non-finite target_pct {raw['target_pct']}"
                )

            rows.append(PortfolioRow(portfolio, symbol, pct))

    # Organize into mapping
    portfolios: Dict[str, Dict[str, float]] = {}
    for row in rows:
        portfolios.setdefault(row.portfolio, {})
        if row.symbol in portfolios[row.portfolio]:
            if row.symbol == "CASH":
                raise PortfolioError(f"Portfolio {row.portfolio}: multiple CASH rows found")
            raise PortfolioError(f"Duplicate symbol '{row.symbol}' in portfolio '{row.portfolio}'")
        portfolios[row.portfolio][row.symbol] = row.target_pct

    # Validate each portfolio
    for name, weights in portfolios.items():
        cash_values = [v for s, v in weights.items() if s == "CASH"]
        if len(cash_values) > 1:
            raise PortfolioError(f"Portfolio {name}: multiple CASH rows found")
        cash_pct = cash_values[0] if cash_values else 0.0
        asset_sum = sum(v for s, v in weights.items() if s != "CASH")

        if cash_values:
            if not allow_margin:
                raise PortfolioError(f"Portfolio {name}: CSV contains CASH but margin is disabled")
            if cash_pct >= 0:
                raise PortfolioError(
                    f"Portfolio {name}: CASH row must be negative, got {cash_pct*100:.2f}%"
                )
            total = asset_sum + cash_pct
            if abs(total - 1.0) > TOLERANCE:
                raise PortfolioError(
                    f"Portfolio {name}: asset weights {asset_sum*100:.2f}% plus CASH {cash_pct*100:.2f}% != 100%"
                )
        else:
            if abs(asset_sum - 1.0) > TOLERANCE:
                raise PortfolioError(
                    f"Portfolio {name}: weights sum to {asset_sum*100:.2f}% (expected 100%)"
                )

    return portfolios
