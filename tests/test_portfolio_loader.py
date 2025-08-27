import sys
from pathlib import Path

import pytest

# Ensure the package root is on the import path when running tests directly
sys.path.append(str(Path(__file__).resolve().parents[1]))

from ibkr_etf_rebalancer.portfolio_loader import load_portfolios, PortfolioError


@pytest.fixture(
    params=[
        (
            "basic",
            """portfolio,symbol,target_pct\nSMURF,VTI,40\nSMURF,VEA,30\nSMURF,BND,30\nBADASS,USMV,60\nBADASS,QUAL,40\nGLTR,IGV,50\nGLTR,XLV,50\n""",
            False,
            {
                "SMURF": {"VTI": 0.40, "VEA": 0.30, "BND": 0.30},
                "BADASS": {"USMV": 0.60, "QUAL": 0.40},
                "GLTR": {"IGV": 0.50, "XLV": 0.50},
            },
        ),
        (
            "with_cash",
            """portfolio,symbol,target_pct\nSMURF,VTI,60\nSMURF,BND,40\nBADASS,SPY,100\nGLTR,GLD,100\nGLTR,GDX,50\nGLTR,CASH,-50\n""",
            True,
            {
                "SMURF": {"VTI": 0.60, "BND": 0.40},
                "BADASS": {"SPY": 1.0},
                "GLTR": {"GLD": 1.0, "GDX": 0.50, "CASH": -0.50},
            },
        ),
    ],
    ids=lambda p: p[0],
)
def valid_csv(tmp_path: Path, request):
    name, csv_content, allow_margin, expected = request.param
    path = tmp_path / f"{name}.csv"
    path.write_text(csv_content)
    return path, allow_margin, expected


def test_load_valid_csv(valid_csv):
    path, allow_margin, expected = valid_csv
    result = load_portfolios(path, allow_margin=allow_margin)
    assert result == expected


@pytest.fixture(
    params=[
        (
            "sum_not_100",
            """portfolio,symbol,target_pct\nSMURF,VTI,50\nSMURF,VEA,30\nSMURF,BND,30\n""",
            False,
            "weights sum to 110.00%",
        ),
        (
            "cash_positive",
            """portfolio,symbol,target_pct\nSMURF,VTI,50\nSMURF,CASH,50\n""",
            True,
            "CASH row must be negative",
        ),
        (
            "multi_cash",
            """portfolio,symbol,target_pct\nSMURF,VTI,100\nSMURF,CASH,-10\nSMURF,CASH,-10\n""",
            True,
            "multiple CASH rows",
        ),
        (
            "cash_not_100",
            """portfolio,symbol,target_pct\nSMURF,VTI,90\nSMURF,CASH,-5\n""",
            True,
            "asset weights 90.00% plus CASH -5.00% != 100%",
        ),
        (
            "cash_without_margin",
            """portfolio,symbol,target_pct\nSMURF,VTI,50\nSMURF,CASH,-50\n""",
            False,
            "margin is disabled",
        ),
        (
            "unknown_portfolio",
            """portfolio,symbol,target_pct\nFOO,VTI,100\n""",
            False,
            "Unknown portfolio",
        ),
    ],
    ids=lambda p: p[0],
)
def invalid_csv(tmp_path: Path, request):
    name, csv_content, allow_margin, message = request.param
    path = tmp_path / f"{name}.csv"
    path.write_text(csv_content)
    return path, allow_margin, message


def test_load_invalid_csv(invalid_csv):
    path, allow_margin, message = invalid_csv
    with pytest.raises(PortfolioError) as exc:
        load_portfolios(path, allow_margin=allow_margin)
    assert message in str(exc.value)
