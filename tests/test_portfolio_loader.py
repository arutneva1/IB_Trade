import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_etf_rebalancer.portfolio_loader import (
    PortfolioLoaderError,
    load_portfolios,
)

DATA_DIR = Path(__file__).parent / "data"


def test_load_portfolios_valid():
    path = DATA_DIR / "portfolios_valid.csv"
    result = load_portfolios(path, allow_margin=False)
    assert result == {
        "SMURF": {"VTI": 40.0, "VEA": 30.0, "BND": 30.0},
        "BADASS": {"VTI": 60.0, "QUAL": 40.0},
        "GLTR": {"IGV": 50.0, "XLV": 50.0},
    }


def test_load_portfolios_with_margin():
    path = DATA_DIR / "portfolios_margin.csv"
    result = load_portfolios(path, allow_margin=True)
    assert result["SMURF"] == {"GLD": 100.0, "GDX": 50.0, "CASH": -50.0}


def test_cash_not_allowed():
    path = DATA_DIR / "portfolios_margin.csv"
    with pytest.raises(PortfolioLoaderError) as exc:
        load_portfolios(path, allow_margin=False)
    assert "allow_margin is false" in str(exc.value)


@pytest.mark.parametrize(
    "fname, substring",
    [
        ("portfolios_invalid_sum.csv", "assets must sum to 100"),
        ("portfolios_invalid_multiple_cash.csv", "multiple CASH"),
        ("portfolios_invalid_unknown.csv", "unknown portfolio"),
        ("portfolios_invalid_non_numeric.csv", "target_pct is not a number"),
        ("portfolios_invalid_cash_positive.csv", "CASH target_pct must be negative"),
    ],
)
def test_load_portfolios_invalid(fname: str, substring: str):
    path = DATA_DIR / fname
    with pytest.raises(PortfolioLoaderError) as exc:
        load_portfolios(path, allow_margin=True)
    assert substring in str(exc.value)
