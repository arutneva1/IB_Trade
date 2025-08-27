"""Utilities for loading model portfolios from CSV.

The file format is documented in :mod:`srs.md` section 3.1 and uses three
model names: ``SMURF``, ``BADASS`` and ``GLTR``.  Each row contains
``portfolio,symbol,target_pct``.  Optionally a portfolio may include a
``CASH`` row with a **negative** ``target_pct`` to encode margin borrowing.

The loader performs three steps:

* **Parsing** – read rows into :class:`PortfolioRow` dataclasses.
* **Validation** – enforce sum rules and one optional ``CASH`` row.
* **Normalization** – return a mapping of portfolio -> symbol -> pct where
  ``CASH`` is preserved as negative.

The functions are pure and do not touch any global state which keeps the
module easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
import csv

VALID_PORTFOLIOS = {"SMURF", "BADASS", "GLTR"}
TOLERANCE = 0.01


class PortfolioLoaderError(ValueError):
    """Raised when the portfolio CSV is invalid."""


@dataclass
class PortfolioRow:
    """Represents a single row of ``portfolios.csv``."""

    portfolio: str
    symbol: str
    target_pct: float


def parse_portfolio_csv(csv_path: Path) -> List[PortfolioRow]:
    """Parse ``portfolios.csv`` into rows.

    Extra columns are ignored.  The caller is responsible for validation.
    """

    rows: List[PortfolioRow] = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"portfolio", "symbol", "target_pct"}
        if not required.issubset(reader.fieldnames or set()):
            missing = required - set(reader.fieldnames or [])
            raise PortfolioLoaderError(f"missing columns: {sorted(missing)}")
        for line_no, raw in enumerate(reader, start=2):  # account for header
            portfolio = raw["portfolio"].strip().upper()
            symbol = raw["symbol"].strip().upper()
            try:
                target_pct = float(raw["target_pct"])
            except (TypeError, ValueError) as exc:  # pragma: no cover - error path
                raise PortfolioLoaderError(f"line {line_no}: target_pct is not a number") from exc
            rows.append(PortfolioRow(portfolio, symbol, target_pct))
    return rows


def load_portfolios(csv_path: Path, *, allow_margin: bool) -> Dict[str, Dict[str, float]]:
    """Load and validate model portfolios from ``csv_path``.

    Parameters
    ----------
    csv_path:
        Path to the ``portfolios.csv`` file.
    allow_margin:
        When ``True`` a portfolio may include a ``CASH`` row with a negative
        percentage.  When ``False`` any ``CASH`` row triggers an error.

    Returns
    -------
    dict
        Mapping of portfolio name to ``{symbol: target_pct}`` where ``CASH``
        is kept negative.
    """

    rows = parse_portfolio_csv(csv_path)
    portfolios: Dict[str, Dict[str, float]] = {}

    for row in rows:
        if row.portfolio not in VALID_PORTFOLIOS:
            raise PortfolioLoaderError(f"unknown portfolio '{row.portfolio}'")
        portfolio = portfolios.setdefault(row.portfolio, {})
        symbol = row.symbol
        pct = row.target_pct

        if symbol == "CASH":
            if not allow_margin:
                raise PortfolioLoaderError("CASH row present but allow_margin is false")
            if "CASH" in portfolio:
                raise PortfolioLoaderError(f"portfolio {row.portfolio} has multiple CASH rows")
            if pct >= 0:
                raise PortfolioLoaderError("CASH target_pct must be negative")
            portfolio["CASH"] = pct
        else:
            if pct <= 0:
                raise PortfolioLoaderError(f"{row.portfolio} {symbol} target_pct must be positive")
            if symbol in portfolio:
                raise PortfolioLoaderError(
                    f"portfolio {row.portfolio} has duplicate symbol {symbol}"
                )
            portfolio[symbol] = pct

    # Validate sums per portfolio
    for name, holdings in portfolios.items():
        cash = holdings.get("CASH")
        asset_sum = sum(pct for sym, pct in holdings.items() if sym != "CASH")
        total = asset_sum + (cash or 0.0)
        if cash is None:
            if abs(asset_sum - 100) > TOLERANCE:
                raise PortfolioLoaderError(f"{name} assets must sum to 100%, got {asset_sum:.2f}%")
        else:
            if abs(total - 100) > TOLERANCE:
                raise PortfolioLoaderError(
                    f"{name} assets plus CASH must sum to 100%, got {total:.2f}%"
                )

    return portfolios
