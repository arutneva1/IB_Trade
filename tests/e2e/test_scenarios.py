import json
import hashlib
import io
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from ibkr_etf_rebalancer.scenario import load_scenario
from ibkr_etf_rebalancer.scenario_runner import run_scenario

FIXTURE_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_text_almost_equal(actual: str, expected: str) -> None:
    num_re = re.compile(r"-?\d+(?:\.\d+)?")
    act_parts = num_re.split(actual)
    exp_parts = num_re.split(expected)
    assert act_parts == exp_parts
    act_nums = [float(x) for x in num_re.findall(actual)]
    exp_nums = [float(x) for x in num_re.findall(expected)]
    assert len(act_nums) == len(exp_nums)
    for a, e in zip(act_nums, exp_nums):
        assert a == pytest.approx(e, rel=1e-6, abs=1e-6)


def _assert_md_almost_equal(actual: Path, expected: Path) -> None:
    def _normalize(text: str) -> str:
        lines = text.strip().splitlines()
        if len(lines) <= 2:
            return text.strip()
        header = lines[:2]
        rows = sorted(lines[2:])
        return "\n".join(header + rows)

    _assert_text_almost_equal(_normalize(actual.read_text()), _normalize(expected.read_text()))


def _read_report(path: Path) -> tuple[str, pd.DataFrame]:
    lines = path.read_text().splitlines()
    meta_lines: list[str] = []
    data_lines: list[str] = []
    in_data = False
    for line in lines:
        if not in_data and line.startswith("symbol"):
            in_data = True
        if in_data:
            data_lines.append(line)
        else:
            if line.strip():
                meta_lines.append(line)
    meta = "\n".join(meta_lines)
    df = pd.read_csv(io.StringIO("\n".join(data_lines)))
    return meta, df


def _assert_csv_almost_equal(actual: Path, expected: Path) -> None:
    meta_a, df_a = _read_report(actual)
    meta_e, df_e = _read_report(expected)
    _assert_text_almost_equal(meta_a, meta_e)
    if "symbol" in df_a.columns:
        df_a = df_a.sort_values("symbol").reset_index(drop=True)
        df_e = df_e.sort_values("symbol").reset_index(drop=True)
    pd.testing.assert_frame_equal(df_a, df_e, rtol=1e-6, atol=1e-6)


_ORDER_RE = re.compile(
    r"Contract\(symbol='(?P<symbol>[^']+)', sec_type='(?P<sec_type>[^']+)', currency='(?P<currency>[^']+)'"
)
_SIDE_RE = re.compile(r"OrderSide.(?P<side>BUY|SELL)")
_LIMIT_RE = re.compile(r"limit_price=(?P<price>[0-9.]+)")


def _parse_order(text: str) -> dict[str, Any]:
    m = _ORDER_RE.search(text)
    if not m:
        raise AssertionError(f"cannot parse order: {text}")
    side = _SIDE_RE.search(text)
    limit = _LIMIT_RE.search(text)
    return {
        "symbol": m.group("symbol"),
        "sec_type": m.group("sec_type"),
        "currency": m.group("currency"),
        "side": side.group("side") if side else None,
        "limit_price": float(limit.group("price")) if limit else None,
    }


FIXTURES = sorted(FIXTURE_DIR.glob("*.yml"))


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda p: p.stem)
def test_scenarios(fixture_path: Path) -> None:
    scenario = load_scenario(fixture_path)
    if scenario.config_overrides.get("rebalance", {}).get("min_order_usd", 1) <= 0:
        scenario.config_overrides.setdefault("rebalance", {})["min_order_usd"] = 1e-9

    result = run_scenario(scenario)

    files = {
        "pre_csv": result.pre_report_csv,
        "pre_md": result.pre_report_md,
        "post_csv": result.post_report_csv,
        "post_md": result.post_report_md,
        "event_log": result.event_log,
    }

    hashes1 = {name: _file_hash(path) for name, path in files.items()}

    result2 = run_scenario(scenario)
    files2 = {
        "pre_csv": result2.pre_report_csv,
        "pre_md": result2.pre_report_md,
        "post_csv": result2.post_report_csv,
        "post_md": result2.post_report_md,
        "event_log": result2.event_log,
    }
    hashes2 = {name: _file_hash(path) for name, path in files2.items()}
    assert hashes1 == hashes2

    golden_dir = GOLDEN_DIR / fixture_path.stem

    _assert_csv_almost_equal(files2["pre_csv"], golden_dir / files2["pre_csv"].name)
    _assert_csv_almost_equal(files2["post_csv"], golden_dir / files2["post_csv"].name)
    _assert_md_almost_equal(files2["pre_md"], golden_dir / files2["pre_md"].name)
    _assert_md_almost_equal(files2["post_md"], golden_dir / files2["post_md"].name)

    events = json.loads(files2["event_log"].read_text())
    placed = [e for e in events if e["type"] == "placed"]
    last_rank = -1
    for e in placed:
        info = _parse_order(e["order"])
        key = (
            f"{info['symbol']}.{info['currency']}" if info["sec_type"] == "CASH" else info["symbol"]
        )
        quote = scenario.quotes[key]
        if info["sec_type"] == "CASH":
            if info["limit_price"] is not None:
                if info["side"] == "BUY":
                    assert info["limit_price"] <= quote.ask + 1e-6
                else:
                    assert info["limit_price"] >= quote.bid - 1e-6
            rank = 0
        elif info["side"] == "SELL":
            if info["limit_price"] is not None:
                assert info["limit_price"] >= quote.bid - 1e-6
            rank = 1
        else:
            if info["limit_price"] is not None:
                assert info["limit_price"] <= quote.ask + 1e-6
            rank = 2
        assert rank >= last_rank
        last_rank = rank
