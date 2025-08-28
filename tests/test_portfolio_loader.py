from pathlib import Path

import pytest

from ibkr_etf_rebalancer.portfolio_loader import load_portfolios, PortfolioError


@pytest.fixture(
    params=[
        (
            "basic",
            """portfolio,symbol,target_pct\nSMURF,VTI,40\nSMURF,VEA,30\nSMURF,BND,30\nBADASS,USMV,60\nBADASS,QUAL,40\nGLTR,IGV,50\nGLTR,XLV,50\n""",
            False,
            1.0,
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
            1.5,
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
    name, csv_content, allow_margin, max_leverage, expected = request.param
    path = tmp_path / f"{name}.csv"
    path.write_text(csv_content)
    return path, allow_margin, max_leverage, expected


def test_load_valid_csv(valid_csv):
    path, allow_margin, max_leverage, expected = valid_csv
    result = load_portfolios(path, allow_margin=allow_margin, max_leverage=max_leverage)
    assert result == expected


@pytest.fixture
def extra_columns_csv(tmp_path: Path):
    """CSV containing optional columns that should be ignored."""
    csv_content = (
        "portfolio,symbol,target_pct,note,min_lot,exchange\n"
        "SMURF,VTI,50,some note,10,NYSE\n"
        "SMURF,VEA,50,other note,5,ARCA\n"
    )
    path = tmp_path / "extra.csv"
    path.write_text(csv_content)
    expected = {"SMURF": {"VTI": 0.50, "VEA": 0.50}}
    return path, expected


def test_load_ignores_extra_columns(extra_columns_csv):
    path, expected = extra_columns_csv
    result = load_portfolios(path)
    assert result == expected


@pytest.fixture(
    params=[
        (
            "sum_not_100",
            """portfolio,symbol,target_pct\nSMURF,VTI,50\nSMURF,VEA,30\nSMURF,BND,30\n""",
            False,
            2.0,
            "weights sum to 110.00%",
        ),
        (
            "cash_positive",
            """portfolio,symbol,target_pct\nSMURF,VTI,50\nSMURF,CASH,50\n""",
            True,
            1.0,
            "CASH row must be negative",
        ),
        (
            "multi_cash",
            """portfolio,symbol,target_pct\nSMURF,VTI,100\nSMURF,CASH,-10\nSMURF,CASH,-10\n""",
            True,
            1.0,
            "multiple CASH rows",
        ),
        (
            "cash_not_100",
            """portfolio,symbol,target_pct\nSMURF,VTI,90\nSMURF,CASH,-5\n""",
            True,
            1.0,
            "asset weights 90.00% plus CASH -5.00% != 100%",
        ),
        (
            "cash_without_margin",
            """portfolio,symbol,target_pct\nSMURF,VTI,50\nSMURF,CASH,-50\n""",
            False,
            1.0,
            "margin is disabled",
        ),
        (
            "unknown_portfolio",
            """portfolio,symbol,target_pct\nFOO,VTI,100\n""",
            False,
            1.0,
            "Unknown portfolio",
        ),
        (
            "negative_pct",
            """portfolio,symbol,target_pct\nSMURF,VTI,-10\n""",
            False,
            1.0,
            "negative target_pct",
        ),
        (
            "pct_gt_100",
            """portfolio,symbol,target_pct\nSMURF,VTI,150\n""",
            False,
            1.0,
            "exceeds 100%",
        ),
        (
            "pct_nan",
            """portfolio,symbol,target_pct\nSMURF,VTI,NaN\n""",
            False,
            1.0,
            "non-finite target_pct",
        ),
        (
            "pct_inf",
            """portfolio,symbol,target_pct\nSMURF,VTI,inf\n""",
            False,
            1.0,
            "non-finite target_pct",
        ),
    ],
    ids=lambda p: p[0],
)
def invalid_csv(tmp_path: Path, request):
    name, csv_content, allow_margin, max_leverage, message = request.param
    path = tmp_path / f"{name}.csv"
    path.write_text(csv_content)
    return path, allow_margin, max_leverage, message


def test_load_invalid_csv(invalid_csv):
    path, allow_margin, max_leverage, message = invalid_csv
    with pytest.raises(PortfolioError) as exc:
        load_portfolios(path, allow_margin=allow_margin, max_leverage=max_leverage)
    assert message in str(exc.value)


@pytest.mark.parametrize(
    "name,csv_content,max_leverage,expect",
    [
        (
            "under_leverage",
            """portfolio,symbol,target_pct\nSMURF,VTI,60\nSMURF,BND,60\nSMURF,CASH,-20\n""",
            1.3,
            {"SMURF": {"VTI": 0.60, "BND": 0.60, "CASH": -0.20}},
        ),
        (
            "at_leverage",
            """portfolio,symbol,target_pct\nSMURF,VTI,100\nSMURF,BND,50\nSMURF,CASH,-50\n""",
            1.5,
            {"SMURF": {"VTI": 1.0, "BND": 0.50, "CASH": -0.50}},
        ),
    ],
    ids=["under_leverage", "at_leverage"],
)
def test_max_leverage_valid(tmp_path: Path, name, csv_content, max_leverage, expect):
    path = tmp_path / f"{name}.csv"
    path.write_text(csv_content)
    result = load_portfolios(path, allow_margin=True, max_leverage=max_leverage)
    assert result == expect


@pytest.mark.parametrize(
    "name,csv_content,max_leverage,message",
    [
        (
            "exceed_leverage",
            """portfolio,symbol,target_pct\nSMURF,VTI,100\nSMURF,BND,50\nSMURF,CASH,-50\n""",
            1.4,
            "asset weights 150.00% exceed max leverage 140.00%",
        ),
    ],
    ids=["exceed_leverage"],
)
def test_max_leverage_invalid(tmp_path: Path, name, csv_content, max_leverage, message):
    path = tmp_path / f"{name}.csv"
    path.write_text(csv_content)
    with pytest.raises(PortfolioError) as exc:
        load_portfolios(path, allow_margin=True, max_leverage=max_leverage)
    assert message in str(exc.value)


@pytest.mark.parametrize("max_leverage", [0, -0.5])
def test_max_leverage_non_positive(tmp_path: Path, max_leverage):
    path = tmp_path / "dummy.csv"
    path.write_text("portfolio,symbol,target_pct\nSMURF,VTI,100\n")
    with pytest.raises(PortfolioError) as exc:
        load_portfolios(path, max_leverage=max_leverage)
    assert "max_leverage must be positive" in str(exc.value)
