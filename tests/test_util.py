"""Tests for generic utility helpers."""

from ibkr_etf_rebalancer.util import from_bps, to_bps


def test_to_bps_and_back() -> None:
    value = 0.0125  # 1.25%
    bps = to_bps(value)
    assert bps == 125.0
    assert from_bps(bps) == value


def test_from_bps_negative() -> None:
    assert from_bps(-50) == -0.005
